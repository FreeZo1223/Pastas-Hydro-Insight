"""NDVI-STAC — bereken NDVI uit Sentinel-2 L2A scenes via een STAC-catalogus.

Skill-contract: ``geo_stack/skills/ndvi-stac.md``.

Flow:
  1. STAC search met BBOX (gereprojecteerd naar EPSG:4326) + datumbereik.
  2. Filter op wolkpercentage.
  3. Lees B04 (red) en B08 (nir) per scene; bereken NDVI.
  4. Aggregeer (mediaan/max/mean) over de tijd-as.
  5. Reproject het eindresultaat naar EPSG:28992.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from pystac_client import Client
from pyproj import Transformer

from geo_stack.core.geo_utils import BBox, hash_bbox, validate_bbox

log = logging.getLogger(__name__)

DEFAULT_STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1"
DEFAULT_COLLECTION = "sentinel-2-l2a"

NODATA_NDVI = -9999.0


class NDVIFetchError(RuntimeError):
    """Generieke fout in de NDVI-pijplijn."""


def fetch_ndvi(
    bbox: BBox,
    date_range: tuple[str, str],
    *,
    max_cloud_cover: int = 20,
    aggregation: str = "median",
    stac_endpoint: str = DEFAULT_STAC_ENDPOINT,
    collection: str = DEFAULT_COLLECTION,
    output_path: Path | str | None = None,
) -> Path:
    """Bereken een geaggregeerd NDVI-raster voor ``bbox`` over ``date_range``.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    date_range
        ``(start_iso, end_iso)``, bv. ``("2025-05-01", "2025-08-31")``.
    max_cloud_cover
        Maximum ``eo:cloud_cover`` per scene (procent).
    aggregation
        ``"median"`` | ``"max"`` | ``"mean"``.
    stac_endpoint
        STAC root URL.
    collection
        STAC collection-id.
    output_path
        Optioneel pad. Standaard ``./ndvi_<bboxhash>_<startdatum>_<einddatum>.tif``.

    Returns
    -------
    pathlib.Path
        Pad naar GeoTIFF in EPSG:28992.
    """
    if aggregation not in {"median", "max", "mean"}:
        raise ValueError(f"aggregation moet 'median'/'max'/'mean' zijn, kreeg {aggregation!r}")

    validate_bbox(bbox, must_be_rd=True)

    bbox_4326 = _reproject_bbox(bbox, "EPSG:28992", "EPSG:4326")

    log.info("STAC search %s @ %s, dates %s", collection, bbox_4326, date_range)
    client = Client.open(stac_endpoint)
    search = client.search(
        collections=[collection],
        bbox=bbox_4326,
        datetime=f"{date_range[0]}/{date_range[1]}",
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
    )
    items = list(search.get_all_items())
    if not items:
        raise NDVIFetchError(
            f"Geen Sentinel-2 scenes gevonden voor bbox={bbox_4326}, "
            f"dates={date_range}, cloud<{max_cloud_cover}%"
        )

    log.info("Gevonden %d scenes na wolkfilter", len(items))

    ndvi_stack, transform_utm, crs_utm = _read_and_compute(items, bbox_4326)
    aggregated = _aggregate(ndvi_stack, aggregation)

    if output_path is None:
        bb_hash = hash_bbox(bbox)
        output_path = Path.cwd() / f"ndvi_{bb_hash}_{date_range[0]}_{date_range[1]}.tif"
    else:
        output_path = Path(output_path)

    _write_geotiff_rd(
        aggregated,
        src_transform=transform_utm,
        src_crs=crs_utm,
        dst_path=output_path,
        dst_bbox_rd=bbox,
        tags={
            "STAC_ENDPOINT": stac_endpoint,
            "COLLECTION": collection,
            "DATE_RANGE": f"{date_range[0]}/{date_range[1]}",
            "SCENE_COUNT": str(len(items)),
            "MAX_CLOUD_COVER": str(max_cloud_cover),
            "AGGREGATION": aggregation,
        },
    )
    return output_path


def _reproject_bbox(bbox: BBox, src_crs: str, dst_crs: str) -> BBox:
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    minx, miny = transformer.transform(bbox[0], bbox[1])
    maxx, maxy = transformer.transform(bbox[2], bbox[3])
    return (minx, miny, maxx, maxy)


def _read_and_compute(items, bbox_4326: BBox):
    """Lees B04/B08 per scene, clip op bbox, bereken NDVI per scene.

    Returns een 3D numpy-array (T, H, W) plus de transform en CRS van de
    UTM-grid waarin de scenes staan. **Skeleton-implementatie** —
    productiecode zou ``stackstac`` of ``rioxarray`` gebruiken om dit
    geheugen-efficiënt te doen.
    """
    import rasterio
    from rasterio.windows import from_bounds

    stack: list[np.ndarray] = []
    transform_out = None
    crs_out = None

    for item in items:
        red_href = item.assets["red"].href
        nir_href = item.assets["nir"].href
        with rasterio.open(red_href) as red_ds, rasterio.open(nir_href) as nir_ds:
            scene_bbox = _reproject_bbox(bbox_4326, "EPSG:4326", red_ds.crs.to_string())
            window = from_bounds(*scene_bbox, transform=red_ds.transform)
            red = red_ds.read(1, window=window).astype("float32")
            nir = nir_ds.read(1, window=window).astype("float32")
            ndvi = np.where(
                (red + nir) > 0,
                (nir - red) / (nir + red),
                NODATA_NDVI,
            )
            ndvi = np.clip(ndvi, -1.0, 1.0)
            stack.append(ndvi)
            if transform_out is None:
                transform_out = red_ds.window_transform(window)
                crs_out = red_ds.crs

    return np.stack(stack, axis=0), transform_out, crs_out


def _aggregate(stack: np.ndarray, method: str) -> np.ndarray:
    masked = np.ma.masked_equal(stack, NODATA_NDVI)
    if method == "median":
        out = np.ma.median(masked, axis=0)
    elif method == "max":
        out = masked.max(axis=0)
    else:
        out = masked.mean(axis=0)
    return out.filled(NODATA_NDVI).astype("float32")


def _write_geotiff_rd(
    array: np.ndarray,
    *,
    src_transform,
    src_crs,
    dst_path: Path,
    dst_bbox_rd: BBox,
    tags: dict[str, str],
) -> None:
    """Schrijf array als GeoTIFF en reproject naar EPSG:28992."""
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    height, width = array.shape
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs,
        "EPSG:28992",
        width,
        height,
        *_extent_from_transform(src_transform, width, height),
        dst_width=width,
        dst_height=height,
    )

    with rasterio.open(
        dst_path,
        "w",
        driver="GTiff",
        height=dst_h,
        width=dst_w,
        count=1,
        dtype="float32",
        crs="EPSG:28992",
        transform=dst_transform,
        nodata=NODATA_NDVI,
        compress="lzw",
    ) as dst:
        out_array = np.empty((dst_h, dst_w), dtype="float32")
        reproject(
            source=array,
            destination=out_array,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:28992",
            resampling=Resampling.bilinear,
            src_nodata=NODATA_NDVI,
            dst_nodata=NODATA_NDVI,
        )
        dst.write(out_array, 1)
        dst.update_tags(**tags, BBOX=",".join(f"{c}" for c in dst_bbox_rd))


def _extent_from_transform(transform, width: int, height: int) -> BBox:
    minx = transform.c
    maxy = transform.f
    maxx = minx + transform.a * width
    miny = maxy + transform.e * height
    return (minx, miny, maxx, maxy)
