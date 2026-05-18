"""Normalizer — valideer een GeoDataFrame en schrijf naar geoptimaliseerde GeoParquet.

CRS-eis: EPSG:28992 (RD-stelsel). Geen stille reprojectie zonder expliciete
``reproject=True``. Geen pass-through van invalide of onbekende CRS-waarden.

Optimalisaties (default aan, ~10–100× snellere bbox-queries op grote bestanden):
- **Z-order (Morton) sort** — ruimtelijk nabije rijen liggen ook fysiek nabij
- **Covering bbox column** — DuckDB en pyarrow kunnen rij-groepen overslaan
  zonder geometrie te parsen
- **ZSTD-compressie** — kleinere bestanden, snellere I/O dan default snappy

Implementatie volgens GeoParquet 1.1.0 spec.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
from shapely import make_valid

from geo_stack.core.geo_utils import CRSValidationError, validate_rd_crs

log = logging.getLogger(__name__)

RD_EPSG_STRING = "EPSG:28992"

# 16-bit Morton — 65536 cellen per as is voldoende voor elke realistische bbox.
_MORTON_BITS = 16
_MORTON_RES = (1 << _MORTON_BITS) - 1  # 65535


def normalize_to_geoparquet(
    gdf: gpd.GeoDataFrame,
    output_path: Path | str,
    *,
    reproject: bool = False,
    drop_invalid: bool = True,
    snake_case_columns: bool = True,
    spatial_sort: bool = True,
    write_bbox: bool = True,
    compression: str = "zstd",
) -> dict[str, Any]:
    """Valideer + normaliseer ``gdf`` en schrijf naar geoptimaliseerde GeoParquet 1.1.0.

    Parameters
    ----------
    gdf
        Te schrijven GeoDataFrame (EPSG:28992 of expliciet met ``reproject=True``).
    output_path
        Doelpad voor het ``.parquet``-bestand.
    reproject
        Bij ``True`` wordt een niet-RD frame stilzwijgend naar EPSG:28992
        getransformeerd. Bij ``False`` raise ``CRSValidationError``.
    drop_invalid
        Verwijder lege/None geometrieën en repareer met ``shapely.make_valid``.
    snake_case_columns
        Hernoem kolommen naar ``snake_case`` (geometry blijft geometry).
    spatial_sort
        Sorteer rijen op Z-order (Morton) curve van het centroid. Geeft
        ruimtelijke clustering zodat bbox-filters rij-groepen overslaan.
        Default ``True``. Zet ``False`` voor zeer kleine sets (<1000 rijen)
        waar de overhead niet loont.
    write_bbox
        Voeg per-feature bbox toe als covering-bbox kolom (GeoParquet 1.1.0).
        Default ``True``. Vereist geopandas ≥1.0; bij oudere versies wordt
        deze optie genegeerd met een waarschuwing.
    compression
        Parquet-compressie. Default ``"zstd"`` (kleiner én sneller dan snappy
        voor geo-data). Andere opties: ``"snappy"``, ``"gzip"``, ``"none"``.

    Returns
    -------
    dict[str, Any]
        Stats over de operatie: ``path``, ``feature_count``, ``dropped``,
        ``crs``, ``bbox``, ``spatially_sorted``, ``has_covering_bbox``.
    """
    output_path = Path(output_path)

    if gdf.empty:
        return {
            "path": output_path,
            "feature_count": 0,
            "dropped": 0,
            "crs": RD_EPSG_STRING,
            "bbox": None,
            "spatially_sorted": False,
            "has_covering_bbox": False,
        }

    if gdf.crs is None:
        raise CRSValidationError(
            "GeoDataFrame heeft geen CRS. Zet expliciet via "
            "gdf.set_crs('EPSG:28992', allow_override=True) als de coördinaten "
            "in RD-stelsel staan."
        )

    if gdf.crs.to_epsg() != 28992:
        if not reproject:
            raise CRSValidationError(
                f"CRS is {gdf.crs.to_string()}, vereist EPSG:28992. "
                "Roep aan met reproject=True om te transformeren."
            )
        log.info("Reproject %s → EPSG:28992", gdf.crs.to_string())
        gdf = gdf.to_crs("EPSG:28992")

    dropped = 0
    if drop_invalid:
        before = len(gdf)
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        gdf["geometry"] = gdf.geometry.apply(make_valid)
        gdf = gdf[~gdf.geometry.is_empty].copy()
        dropped = before - len(gdf)
        if dropped:
            log.warning("%d invalide/lege geometrieën gedropt", dropped)

    validate_rd_crs(gdf, strict=True, check_bounds=True)

    if snake_case_columns:
        gdf = gdf.rename(columns={c: _snake_case(c) for c in gdf.columns})

    sorted_flag = False
    if spatial_sort and len(gdf) >= 100:
        gdf = _z_order_sort(gdf)
        sorted_flag = True

    output_path.parent.mkdir(parents=True, exist_ok=True)

    write_kwargs: dict[str, Any] = {
        "schema_version": "1.1.0",
        "compression": compression,
    }
    bbox_written = False
    if write_bbox:
        try:
            gdf.to_parquet(output_path, write_covering_bbox=True, **write_kwargs)
            bbox_written = True
        except TypeError:
            # geopandas <1.0 kent write_covering_bbox niet
            log.warning(
                "geopandas %s ondersteunt write_covering_bbox niet. "
                "Upgrade naar ≥1.0 voor bbox-query optimalisatie.",
                gpd.__version__,
            )
            gdf.to_parquet(output_path, **write_kwargs)
    else:
        gdf.to_parquet(output_path, **write_kwargs)

    return {
        "path": output_path,
        "feature_count": int(len(gdf)),
        "dropped": int(dropped),
        "crs": RD_EPSG_STRING,
        "bbox": tuple(gdf.total_bounds.tolist()),
        "spatially_sorted": sorted_flag,
        "has_covering_bbox": bbox_written,
    }


def _z_order_sort(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Sorteer GeoDataFrame op Z-order (Morton) curve van centroids.

    Geeft ruimtelijke clustering: nabije features eindigen in opeenvolgende
    rijen, waardoor parquet rij-groepen efficiënt geskipt kunnen worden bij
    bbox-filters. Z-order is een goedkope benadering van Hilbert (~90% van de
    winst, ~10% van de complexiteit).
    """
    centroids = gdf.geometry.centroid
    xs = centroids.x.to_numpy()
    ys = centroids.y.to_numpy()
    xmin, xmax = xs.min(), xs.max()
    ymin, ymax = ys.min(), ys.max()
    x_span = max(xmax - xmin, 1e-9)
    y_span = max(ymax - ymin, 1e-9)
    # Schaal naar 16-bit grid
    xi = np.clip(((xs - xmin) / x_span * _MORTON_RES).astype(np.uint32), 0, _MORTON_RES)
    yi = np.clip(((ys - ymin) / y_span * _MORTON_RES).astype(np.uint32), 0, _MORTON_RES)
    keys = _morton_encode(xi, yi)
    order = np.argsort(keys, kind="stable")
    return gdf.iloc[order].reset_index(drop=True)


def _morton_encode(xi: np.ndarray, yi: np.ndarray) -> np.ndarray:
    """Vectorized 16-bit Morton (Z-order) interleave: keys = bit_interleave(x, y)."""
    return _bit_spread(xi) | (_bit_spread(yi) << 1)


def _bit_spread(n: np.ndarray) -> np.ndarray:
    """Spreid 16 bits naar even posities van een 32-bit getal."""
    n = n.astype(np.uint32)
    n = (n | (n << 8)) & np.uint32(0x00FF00FF)
    n = (n | (n << 4)) & np.uint32(0x0F0F0F0F)
    n = (n | (n << 2)) & np.uint32(0x33333333)
    n = (n | (n << 1)) & np.uint32(0x55555555)
    return n


_SNAKE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _snake_case(name: str) -> str:
    if name == "geometry":
        return name
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    s1 = _SNAKE_RE_1.sub(r"\1_\2", ascii_name)
    s2 = _SNAKE_RE_2.sub(r"\1_\2", s1).lower()
    s3 = _NON_ALNUM.sub("_", s2).strip("_")
    return s3 or "col"
