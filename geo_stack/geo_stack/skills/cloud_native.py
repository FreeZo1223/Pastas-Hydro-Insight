"""Cloud-native streaming voor grote Nederlandse geo-datasets.

Gebruikt DuckDB + httpfs + spatial extension om remote bestanden
(GPKG-in-ZIP, COG, GeoParquet) te bevragen met ST_Intersects zonder
volledige download. Patroon afgeleid uit SMP/Potentieanalyse.

Ondersteunde bronnen (zie ``services.yaml``):
- 3DBAG (GPKG in ZIP, ~8 GB) — panden met 3D-geometrie
- BAG-extract (GeoPackage via PDOK) — adresseerbare objecten
- BRT Top10NL (GeoPackage in ZIP)
- BGT bulk-download (GeoPackage via PDOK API)

Wanneer gebruiken t.o.v. WFS (``bgt_fetcher``):
    < 5 000 features  → WFS is eenvoudiger
    ≥ 5 000 features  → DuckDB streaming wint altijd op snelheid
    Heel NL of provincie → altijd cloud-native

Prestaties (empirisch, SMP/Potentieanalyse):
    3DBAG één gemeente (~30k panden): 15–60s
    WFS bgt:pand zelfde gemeente:    3–8 min (paginatie)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
from pyproj import Transformer
from shapely import wkt as shapely_wkt
from shapely.geometry import box

from geo_stack.core.geo_utils import BBox, validate_bbox, validate_rd_crs

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


def _get_duckdb():
    """Lazy-import en setup van DuckDB met spatial+httpfs extensies."""
    try:
        import duckdb
    except ImportError as exc:
        raise ImportError(
            "duckdb is niet geïnstalleerd. Run: pip install duckdb"
        ) from exc

    con = duckdb.connect()
    con.execute("""
        INSTALL spatial; LOAD spatial;
        INSTALL httpfs;  LOAD httpfs;
        SET enable_progress_bar = false;
    """)
    return con


def stream_3dbag(
    bbox: BBox,
    *,
    layer: str = "lod22_2d",
    columns: list[str] | None = None,
    url: str = "https://data.3dbag.nl/v20250903/3dbag_nl.gpkg.zip",
    internal_gpkg: str = "3dbag_nl.gpkg",
) -> gpd.GeoDataFrame:
    """Stream 3DBAG-panden binnen ``bbox`` zonder volledige download.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    layer
        ``"lod22_2d"`` (vlakken) of ``"pand"`` (attributenlaag).
    columns
        Subset van kolommen. ``None`` = alles. ``"identificatie"`` is
        altijd aanwezig.
    url
        Directe URL naar het 3DBAG GPKG-ZIP bestand op data.3dbag.nl.
        Controleer https://3dbag.nl voor nieuwste versienummer.
    internal_gpkg
        Bestandsnaam van de GPKG binnen de ZIP.

    Returns
    -------
    geopandas.GeoDataFrame
        In EPSG:28992. Kolom ``geometry`` is de 2D-footprint.
    """
    validate_bbox(bbox, must_be_rd=True)
    minx_i, miny_i, maxx_i, maxy_i = (int(c) for c in bbox)
    # Bbox als 2D-polygoon voor secondary WHERE-filter.
    boundary_wkt = box(*bbox).wkt
    # ST_Force2D: 3DBAG v2025 slaat geometrie op als compound 3D CRS (EPSG:7415).
    # SELECT * zou de ruwe geom-kolom meenemen die DuckDB→NumPy niet kan converteren.
    # Sluit geom altijd uit en vervang door WKT via ST_Force2D.
    if columns is None:
        col_expr = "* EXCLUDE (geom), ST_AsText(ST_Force2D(geom)) AS wkt"
    else:
        col_expr = _col_sql(columns, always=["identificatie", "ST_AsText(ST_Force2D(geom)) AS wkt"])
    vsi_path = f"/vsizip//vsicurl/{url}/{internal_gpkg}"

    # spatial_filter pushes de bbox-filter door naar GDAL's OGR-spatialindex in de GPKG,
    # zodat DuckDB niet de volledige 8GB-tabel hoeft te scannen.
    # Zonder spatial_filter blokkeert ST_Force2D() in WHERE de index-pushdown.
    filter_wkt = (
        f"POLYGON(({minx_i} {miny_i},{maxx_i} {miny_i},"
        f"{maxx_i} {maxy_i},{minx_i} {maxy_i},{minx_i} {miny_i}))"
    )

    log.info("3DBAG streaming %s @ %s via DuckDB", layer, bbox)
    con = _get_duckdb()
    query = f"""
        SELECT {col_expr}
        FROM st_read('{vsi_path}', layer := '{layer}',
                     spatial_filter := ST_GeomFromText('{filter_wkt}'))
        WHERE ST_Intersects(ST_Force2D(geom), ST_GeomFromText('{boundary_wkt}'))
    """
    df = con.execute(query).fetchdf()
    con.close()

    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

    df["geometry"] = df["wkt"].apply(shapely_wkt.loads)
    gdf = gpd.GeoDataFrame(df.drop(columns=["wkt"]), geometry="geometry", crs="EPSG:28992")
    validate_rd_crs(gdf, strict=True)
    log.info("3DBAG: %d panden geladen", len(gdf))
    return gdf


def stream_bag_extract(
    bbox: BBox,
    *,
    object_type: str = "verblijfsobject",
    url: str = "https://service.pdok.nl/lv/bag/atom/v1_0/downloads/bag-light.gpkg",
    columns: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """Stream BAG-objecten uit de PDOK BAG Light GeoPackage.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    object_type
        BAG-laagnaam: ``"verblijfsobject"``, ``"pand"``, ``"nummeraanduiding"``.
    url
        Directe URL naar BAG Light GPKG op PDOK.
    columns
        Subset van kolommen. ``None`` = alles.
    """
    validate_bbox(bbox, must_be_rd=True)
    boundary_wkt = box(*bbox).wkt
    col_expr = _col_sql(columns, always=["identificatie", "ST_AsText(geom) AS wkt"])

    log.info("BAG streaming %s @ %s via DuckDB", object_type, bbox)
    con = _get_duckdb()
    query = f"""
        SELECT {col_expr}
        FROM st_read('/vsicurl/{url}', layer := '{object_type}')
        WHERE ST_Intersects(geom, ST_GeomFromText('{boundary_wkt}'))
    """
    df = con.execute(query).fetchdf()
    con.close()

    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

    df["geometry"] = df["wkt"].apply(shapely_wkt.loads)
    gdf = gpd.GeoDataFrame(df.drop(columns=["wkt"]), geometry="geometry", crs="EPSG:28992")
    validate_rd_crs(gdf, strict=True)
    return gdf


def stream_geoparquet(
    bbox: BBox,
    *,
    url: str,
    crs_source: str = "EPSG:28992",
    columns: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """Stream een remote GeoParquet-bestand met BBOX-filter via DuckDB.

    Geschikt voor cloud-native Parquet-bestanden (bijv. STAC-assets,
    NSO-downloads, eigen opgeslagen outputs).

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    url
        HTTPS-URL naar een GeoParquet-bestand.
    crs_source
        CRS van het bronbestand. Wordt gebruikt voor de BBOX-clip.
        Als dit afwijkt van EPSG:28992, wordt de bbox getransformeerd.
    """
    validate_bbox(bbox, must_be_rd=True)
    fetch_bbox = _transform_bbox_if_needed(bbox, "EPSG:28992", crs_source)
    col_expr = "*" if not columns else ", ".join(columns)

    log.info("GeoParquet streaming %s @ %s", url, bbox)
    con = _get_duckdb()
    minx, miny, maxx, maxy = fetch_bbox
    # GeoParquet bounding-box filter via Parquet min/max statistics
    query = f"""
        SELECT {col_expr}
        FROM read_parquet('/vsicurl/{url}')
        WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx}
          AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
    """
    df = con.execute(query).fetchdf()
    con.close()

    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs=crs_source)

    gdf = gpd.GeoDataFrame(df, crs=crs_source)
    if crs_source != "EPSG:28992":
        gdf = gdf.to_crs("EPSG:28992")
    validate_rd_crs(gdf, strict=True)
    return gdf


# --- helpers ---

def _col_sql(columns: list[str] | None, always: list[str]) -> str:
    """Bouw een SELECT-expressie. ``always``-kolommen worden altijd opgenomen."""
    if columns is None:
        return "*"
    merged = list(dict.fromkeys(always + columns))  # dedup, volgorde bewaren
    return ", ".join(merged)


def _transform_bbox_if_needed(bbox: BBox, src: str, dst: str) -> BBox:
    if src == dst:
        return bbox
    transformer = Transformer.from_crs(src, dst, always_xy=True)
    minx, miny = transformer.transform(bbox[0], bbox[1])
    maxx, maxy = transformer.transform(bbox[2], bbox[3])
    return (minx, miny, maxx, maxy)
