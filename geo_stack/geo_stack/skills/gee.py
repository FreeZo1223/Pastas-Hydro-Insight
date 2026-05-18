"""GEE-fetcher — fetch Google Earth Engine ImageCollections direct via computePixels.

Skill-contract: ``skills/gee-fetcher.md``.

Patroon afgeleid uit SMP/Potentieanalyse (`acquire_municipality.py`). Skipt
Google Drive: streamt tegels via ``ee.data.computePixels`` en stitcht naar
één GeoTIFF.

Authenticatie:
    Eenmalig: ``earthengine authenticate`` (interactief)
    Of via service account: ``ee.Initialize(credentials=ee.ServiceAccountCredentials(...))``

CRS: input bbox in EPSG:28992 (RD New), output GeoTIFF in EPSG:32631 (UTM 31N)
voor compatibiliteit met AlphaEarth-collectie.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from geo_stack.core.geo_utils import BBox, validate_bbox

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


# AlphaEarth — 64-band annuele satelliet-embeddings (Google/DeepMind, 10m resolutie)
ALPHA_EARTH_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
ALPHA_EARTH_BANDS = 64
ALPHA_EARTH_RESOLUTION_M = 10
ALPHA_EARTH_OUTPUT_CRS = "EPSG:32631"  # UTM zone 31N

# computePixels-limiet: 50 MB per request. Voor 64 banden float32:
# 64 * 4 bytes * N² < 50 MB  →  N < ~440 px. Met marge: 384 px (~37 MB).
DEFAULT_TILE_PIXELS = 384


class GEEFetchError(RuntimeError):
    """Fout in de GEE-fetch pijplijn."""


class GEENotAuthenticatedError(GEEFetchError):
    """earthengine-api niet geauthenticeerd. Run `earthengine authenticate`."""


def _import_ee_dependencies():
    """Import dependencies en raise duidelijke fout bij ontbrekende installatie."""
    try:
        import ee  # type: ignore[import-not-found]
        import numpy as np
        import rasterio
        from rasterio.transform import Affine
    except ImportError as exc:
        raise GEEFetchError(
            f"Ontbrekende dependency: {exc}. "
            "Installeer via: pip install 'geo_stack[gee]' "
            "(voegt earthengine-api toe; rasterio is core dependency)"
        ) from exc
    return ee, np, rasterio, Affine


def _initialize_ee(service_account_json: Path | str | None = None) -> None:
    """Initialiseer Earth Engine met optionele service account."""
    import ee  # type: ignore[import-not-found]

    try:
        if service_account_json:
            credentials = ee.ServiceAccountCredentials(
                email=None, key_file=str(service_account_json)
            )
            ee.Initialize(credentials=credentials)
        else:
            ee.Initialize()
    except Exception as exc:
        raise GEENotAuthenticatedError(
            f"Earth Engine init faalde: {exc}. "
            "Run `earthengine authenticate` of geef service_account_json mee."
        ) from exc


def _reproject_bbox_to_utm31(bbox_rd: BBox) -> BBox:
    """Herproject RD-New bbox-hoeken naar UTM 31N (EPSG:32631)."""
    from pyproj import Transformer

    tr = Transformer.from_crs(28992, 32631, always_xy=True)
    xs, ys = zip(
        *[
            tr.transform(bbox_rd[0], bbox_rd[1]),
            tr.transform(bbox_rd[2], bbox_rd[1]),
            tr.transform(bbox_rd[0], bbox_rd[3]),
            tr.transform(bbox_rd[2], bbox_rd[3]),
        ]
    )
    return min(xs), min(ys), max(xs), max(ys)


def fetch_alpha_earth(
    bbox: BBox,
    *,
    year: int,
    output_path: Path | str,
    tile_pixels: int = DEFAULT_TILE_PIXELS,
    service_account_json: Path | str | None = None,
) -> Path:
    """Fetch AlphaEarth 64-band annuele embeddings via ``ee.data.computePixels``.

    Skipt Google Drive: tegels worden direct gestreamd en gestitcht.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992 (RD New). Wordt automatisch
        gereprojecteerd naar UTM 31N voor de GEE-call.
    year
        Jaar voor de annuele embedding (bijv. 2024).
    output_path
        Doelpad voor GeoTIFF (LZW-gecomprimeerd, 64 banden float32).
    tile_pixels
        Tile-grootte in pixels. Default 384 (~37 MB per call, onder 50 MB limiet).
    service_account_json
        Optioneel pad naar service account JSON. ``None`` = user auth via
        ``earthengine authenticate``.

    Returns
    -------
    pathlib.Path
        Pad naar de geschreven GeoTIFF (EPSG:32631).

    Raises
    ------
    GEENotAuthenticatedError
        Als Earth Engine niet geïnitialiseerd kan worden.
    GEEFetchError
        Bij ontbrekende dependencies of fetch-fouten.
    """
    validate_bbox(bbox, must_be_rd=True)
    ee, np, rasterio, Affine = _import_ee_dependencies()
    _initialize_ee(service_account_json)

    bbox_utm = _reproject_bbox_to_utm31(bbox)
    xmin, ymin, xmax, ymax = bbox_utm

    # Snap naar 10m grid voor pixel-alignment met AlphaEarth
    res = ALPHA_EARTH_RESOLUTION_M
    xmin = (xmin // res) * res
    ymin = (ymin // res) * res
    xmax = ((xmax // res) + 1) * res
    ymax = ((ymax // res) + 1) * res
    width = int((xmax - xmin) / res)
    height = int((ymax - ymin) / res)
    log.info(
        "AlphaEarth %s: UTM31N bbox %.0f,%.0f → %.0f,%.0f (%d×%d px @%dm)",
        year, xmin, ymin, xmax, ymax, width, height, res,
    )

    coll = (
        ee.ImageCollection(ALPHA_EARTH_COLLECTION)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(
            ee.Geometry.Rectangle([xmin, ymin, xmax, ymax], ALPHA_EARTH_OUTPUT_CRS, False)
        )
    )
    # toFloat() forceert float32 ndarray (default = float64), halveert payload
    img = coll.mosaic().toFloat()

    full = np.zeros((ALPHA_EARTH_BANDS, height, width), dtype=np.float32)
    n_tiles_x = (width + tile_pixels - 1) // tile_pixels
    n_tiles_y = (height + tile_pixels - 1) // tile_pixels
    n_tiles_total = n_tiles_x * n_tiles_y
    log.info("Fetching %d tiles (%d×%d px each)", n_tiles_total, tile_pixels, tile_pixels)

    band_names = [f"A{i:02d}" for i in range(ALPHA_EARTH_BANDS)]
    failed_tiles: list[tuple[int, int]] = []
    t_total = time.time()
    done = 0

    for ty in range(n_tiles_y):
        for tx in range(n_tiles_x):
            x0_px = tx * tile_pixels
            y0_px = ty * tile_pixels
            w_t = min(tile_pixels, width - x0_px)
            h_t = min(tile_pixels, height - y0_px)
            tx_utm = xmin + x0_px * res
            ty_utm = ymax - y0_px * res

            try:
                result = ee.data.computePixels(
                    {
                        "expression": img,
                        "fileFormat": "NUMPY_NDARRAY",
                        "grid": {
                            "dimensions": {"width": w_t, "height": h_t},
                            "affineTransform": {
                                "scaleX": res, "shearX": 0, "translateX": float(tx_utm),
                                "shearY": 0, "scaleY": -res, "translateY": float(ty_utm),
                            },
                            "crsCode": ALPHA_EARTH_OUTPUT_CRS,
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001 — GEE raises generic exceptions
                log.warning("Tile (%d,%d) FAILED: %s", tx, ty, exc)
                failed_tiles.append((tx, ty))
                continue

            arr = np.array(result)
            for b, name in enumerate(band_names):
                full[b, y0_px : y0_px + h_t, x0_px : x0_px + w_t] = arr[name]
            done += 1
            log.debug("Tile %d/%d done (%dx%d)", done, n_tiles_total, w_t, h_t)

    if failed_tiles:
        log.warning("%d/%d tiles faalden", len(failed_tiles), n_tiles_total)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    transform = Affine(res, 0, xmin, 0, -res, ymax)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": ALPHA_EARTH_BANDS,
        "dtype": "float32",
        "crs": ALPHA_EARTH_OUTPUT_CRS,
        "transform": transform,
        "compress": "LZW",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(full)

    size_mb = output_path.stat().st_size / 1e6
    elapsed = time.time() - t_total
    log.info("Wrote %s (%.1f MB) in %.0fs", output_path.name, size_mb, elapsed)
    return output_path
