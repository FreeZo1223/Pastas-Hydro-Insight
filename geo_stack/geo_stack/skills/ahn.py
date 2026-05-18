"""AHN-fetcher — haalt AHN4 hoogteraster op via PDOK WCS of COG-streaming.

CRS: EPSG:28992. NoData = -9999. Output: GeoTIFF (Float32).

Twee modi:
- WCS  : PDOK WCS GetCoverage — snel voor kleine AOIs (< ~25 Mpx bij doelresolutie)
- COG  : rasterio /vsicurl/ via PDOK OGC API — geen grootte-limiet, cloud-native

``fetch_method="auto"`` schakelt automatisch naar COG als het pixel-budget te groot
wordt voor WCS (> WCS_PIXEL_LIMIT of bbox-kantlengte > MAX_TILE_EXTENT_M).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from geo_stack.core.geo_utils import BBox, hash_bbox, http_session, validate_bbox

log = logging.getLogger(__name__)

AHN_WCS_ENDPOINT = "https://service.pdok.nl/rws/actueel-hoogtebestand-nederland/wcs/v1_0"
AHN_STAC_BASE = "https://api.pdok.nl/rws/ahn/ogc/v1_0"

# PDOK biedt uitsluitend 0.5m source-coverages aan; 5m wordt via WCS scaleSize afgeleid.
COVERAGE_BY_PRODUCT: dict[str, str] = {
    "DSM": "dsm_05m",
    "DTM": "dtm_05m",
}
AHN_COG_COLLECTIONS = COVERAGE_BY_PRODUCT

MAX_TILE_EXTENT_M = 5_000.0
# Veilige bovengrens voor WCS: ~4900×4900 px (marge onder PDOK-limiet van 5000×5000)
WCS_PIXEL_LIMIT = 24_000_000


class AHNFetchError(RuntimeError):
    pass


# ── Publieke API ──────────────────────────────────────────────────────────────

def fetch_ahn_tile(
    bbox: BBox,
    product: str,
    *,
    resolution: float = 0.5,
    output_path: Path | str | None = None,
    version: str = "AHN4",
    endpoint: str = AHN_WCS_ENDPOINT,
    fetch_method: Literal["auto", "wcs", "cog"] = "auto",
) -> Path:
    """Haal één AHN-tile binnen ``bbox`` als GeoTIFF (sync).

    Parameters
    ----------
    product
        ``"DSM"`` of ``"DTM"``.
    resolution
        ``0.5`` of ``5.0`` meter.
    fetch_method
        ``"auto"``  — COG bij grote AOI (>WCS_PIXEL_LIMIT of kantlengte > 5km), anders WCS.
        ``"wcs"``   — altijd WCS (geeft AHNFetchError bij overschrijding WCS-limiet).
        ``"cog"``   — altijd COG via PDOK OGC API + rasterio /vsicurl/.
    """
    if product not in {"DSM", "DTM"}:
        raise ValueError(f"product moet 'DSM' of 'DTM' zijn, kreeg {product!r}")
    if resolution not in {0.5, 5.0}:
        raise ValueError(f"resolution moet 0.5 of 5.0 zijn, kreeg {resolution!r}")

    validate_bbox(bbox, must_be_rd=True)
    minx, miny, maxx, maxy = bbox
    width_m, height_m = maxx - minx, maxy - miny
    width_px = width_m / resolution
    height_px = height_m / resolution

    use_cog = _should_use_cog(fetch_method, width_px, height_px, width_m, height_m)

    if use_cog:
        log.info(
            "AHN4 %s: %.0f×%.0f px (%.1f km²) → COG-modus",
            product, width_px, height_px, width_m * height_m / 1e6,
        )
        return fetch_ahn_cog(
            bbox, product,
            resolution=resolution,
            output_path=output_path,
            version=version,
        )

    # WCS-pad: harde controle op grootte-limiet
    if resolution == 0.5 and (width_m > MAX_TILE_EXTENT_M or height_m > MAX_TILE_EXTENT_M):
        raise AHNFetchError(
            f"WCS-kantlengte {(width_m, height_m)} > {MAX_TILE_EXTENT_M}m bij 0.5m. "
            "Gebruik fetch_method='cog' of fetch_method='auto', of verlaag de resolutie."
        )

    return _fetch_via_wcs(
        bbox, product,
        resolution=resolution,
        output_path=output_path,
        version=version,
        endpoint=endpoint,
    )


async def async_fetch_ahn_tile(
    bbox: BBox,
    product: str,
    *,
    resolution: float = 0.5,
    output_path: Path | str | None = None,
    version: str = "AHN4",
    endpoint: str = AHN_WCS_ENDPOINT,
    fetch_method: Literal["auto", "wcs", "cog"] = "auto",
) -> Path:
    """Async variant van fetch_ahn_tile — voor gebruik in asyncio.gather()."""
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: fetch_ahn_tile(
            bbox, product,
            resolution=resolution,
            output_path=output_path,
            version=version,
            endpoint=endpoint,
            fetch_method=fetch_method,
        ),
    )


def fetch_ahn_cog(
    bbox: BBox,
    product: str,
    *,
    resolution: float = 0.5,
    output_path: Path | str | None = None,
    version: str = "AHN4",
    stac_base: str = AHN_STAC_BASE,
) -> Path:
    """Stream AHN4 COG-tiles via rasterio /vsicurl/ (geen WCS-grootte-limiet).

    Vraagt de PDOK OGC API voor tile-URLs, opent elke tile met rasterio
    via /vsicurl/, merget ze en clipt naar ``bbox`` bij de gevraagde ``resolution``.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    product
        ``"DSM"`` of ``"DTM"``.
    resolution
        Doelresolutie in meter (bijv. 0.5, 1.0, 5.0).
    """
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.merge import merge as rasterio_merge
        from pyproj import Transformer
    except ImportError as exc:
        raise ImportError(
            "rasterio en pyproj zijn vereist voor COG-modus. "
            "Installeer met: pip install rasterio pyproj"
        ) from exc

    collection = AHN_COG_COLLECTIONS.get(product)
    if not collection:
        raise ValueError(f"product moet 'DSM' of 'DTM' zijn, kreeg {product!r}")

    validate_bbox(bbox, must_be_rd=True)
    minx, miny, maxx, maxy = bbox

    # PDOK OGC API accepteert bbox in WGS84
    t = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    lon_min, lat_min = t.transform(minx, miny)
    lon_max, lat_max = t.transform(maxx, maxy)

    session = http_session()
    r = session.get(
        f"{stac_base}/collections/{collection}/items",
        params={
            "bbox": f"{lon_min:.6f},{lat_min:.6f},{lon_max:.6f},{lat_max:.6f}",
            "limit": 100,
        },
        timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("features", [])

    if not items:
        raise AHNFetchError(
            f"Geen AHN4 {product} COG-tiles gevonden voor bbox {bbox!r}. "
            "Controleer of de bbox geldig is in Nederland."
        )

    cog_urls = [u for u in (_extract_tile_url(it) for it in items) if u]
    if not cog_urls:
        raise AHNFetchError(
            f"STAC-items gevonden ({len(items)}) maar geen download-URLs extraheerbaar. "
            "Controleer de OGC API-respons."
        )

    log.info("AHN4 COG %s: %d tile(s) streamen @ %.1fm", product, len(cog_urls), resolution)

    vsi_urls = [f"/vsicurl/{u}" if u.startswith("http") else u for u in cog_urls]
    datasets = [rasterio.open(u) for u in vsi_urls]
    src_crs = datasets[0].crs
    src_nodata = datasets[0].nodata if datasets[0].nodata is not None else -9999.0

    try:
        merged, merge_transform = rasterio_merge(
            datasets,
            bounds=(minx, miny, maxx, maxy),
            res=resolution,
            resampling=Resampling.bilinear,
            nodata=src_nodata,
        )
    finally:
        for ds in datasets:
            ds.close()

    if output_path is None:
        bb_hash = hash_bbox(bbox)
        output_path = Path.cwd() / f"ahn_{product.lower()}_cog_{resolution}m_{bb_hash}.tif"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "count": 1,
        "height": merged.shape[1],
        "width": merged.shape[2],
        "transform": merge_transform,
        "crs": src_crs or "EPSG:28992",
        "nodata": -9999.0,
        "compress": "lzw",
        "bigtiff": "IF_SAFER",
    }
    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(merged[0].astype("float32"), 1)

    _stamp_metadata(output_path, ahn_version=version, product=product,
                    resolution=resolution, bbox=bbox)
    log.info(
        "AHN4 COG opgeslagen: %s (%d×%d px)",
        output_path.name, merged.shape[2], merged.shape[1],
    )
    return output_path


# ── Interne helpers ───────────────────────────────────────────────────────────

def _should_use_cog(
    fetch_method: str,
    width_px: float,
    height_px: float,
    width_m: float,
    height_m: float,
) -> bool:
    if fetch_method == "cog":
        return True
    if fetch_method == "wcs":
        return False
    # "auto": kies COG als het pixel-budget of de kantlengte te groot is voor WCS
    return (
        width_px * height_px > WCS_PIXEL_LIMIT
        or width_m > MAX_TILE_EXTENT_M
        or height_m > MAX_TILE_EXTENT_M
    )


def _fetch_via_wcs(
    bbox: BBox,
    product: str,
    *,
    resolution: float,
    output_path: Path | str | None,
    version: str,
    endpoint: str,
) -> Path:
    coverage = COVERAGE_BY_PRODUCT[product]
    minx, miny, maxx, maxy = bbox
    width_m, height_m = maxx - minx, maxy - miny
    width_px = int(round(width_m / resolution))
    height_px = int(round(height_m / resolution))

    if output_path is None:
        bb_hash = hash_bbox(bbox)
        output_path = Path.cwd() / f"ahn_{product.lower()}_{resolution}m_{bb_hash}.tif"
    else:
        output_path = Path(output_path)

    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": coverage,
        "format": "image/tiff",
        "subsettingCRS": "http://www.opengis.net/def/crs/EPSG/0/28992",
        "outputCRS": "http://www.opengis.net/def/crs/EPSG/0/28992",
        "subset": [f"X({minx},{maxx})", f"Y({miny},{maxy})"],
        "scaleSize": f"X({width_px}),Y({height_px})",
    }

    session = http_session()
    log.info("WCS GetCoverage %s @ %s (%.0fx%.0f px)", coverage, bbox, width_px, height_px)
    resp = session.get(endpoint, params=params, timeout=300, stream=True)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "tiff" not in content_type.lower():
        raise AHNFetchError(
            f"Onverwachte Content-Type {content_type!r}; "
            f"eerste 256 bytes: {resp.content[:256]!r}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)

    _stamp_metadata(output_path, ahn_version=version, product=product,
                    resolution=resolution, bbox=bbox)
    return output_path


def _extract_tile_url(item: dict) -> str | None:
    """Extraheer download-URL uit een OGC API / STAC item."""
    # STAC 1.0 assets
    for key, asset in item.get("assets", {}).items():
        href = asset.get("href", "")
        media = asset.get("type", "")
        if href.endswith(".tif") or "tiff" in media or key in ("data", "download"):
            return href
    # OGC API / Atom links
    for link in item.get("links", []):
        rel = link.get("rel", "")
        href = link.get("href", "")
        if rel in ("enclosure", "data", "download") and href:
            return href
    # Laatste poging: elk .tif-link
    for link in item.get("links", []):
        if link.get("href", "").endswith(".tif"):
            return link["href"]
    return None


def _stamp_metadata(
    path: Path, *, ahn_version: str, product: str, resolution: float, bbox: BBox
) -> None:
    try:
        import rasterio
    except ImportError:
        log.warning("rasterio niet geïnstalleerd; metadata-stamp overgeslagen")
        return

    with rasterio.open(path, "r+") as ds:
        ds.update_tags(
            AHN_VERSION=ahn_version,
            PRODUCT=product,
            RESOLUTION=str(resolution),
            BBOX=",".join(str(c) for c in bbox),
        )
