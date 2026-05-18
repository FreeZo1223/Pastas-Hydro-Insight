"""BGT-fetcher — haalt BGT FeatureTypes op via PDOK OGC API Features.

De oude WFS-endpoint (service.pdok.nl/lv/bgt/wfs/v1_0) is per 2025 offline.
Nieuwe endpoint: api.pdok.nl/lv/bgt/ogc/v1_0 (OGC API Features / GeoJSON).

CRS: EPSG:28992. Max ~10.000 features per request (paginatie via next-link).
"""

from __future__ import annotations

import asyncio
import logging

import geopandas as gpd

from geo_stack.core.geo_utils import BBox, http_session, validate_bbox, validate_rd_crs

log = logging.getLogger(__name__)

BGT_OGC_ENDPOINT = "https://api.pdok.nl/lv/bgt/ogc/v1_0"
OGC_PAGE_SIZE = 1_000

# OGC API laagnamen (zonder "bgt:" prefix)
# Gebruik ook de typeName zonder prefix als input (beide worden geaccepteerd).
BGT_LAYER_ALIASES: dict[str, str] = {
    "bgt:pand": "pand",
    "bgt:wegdeel": "wegdeel",
    "bgt:begroeidterreindeel": "begroeidterreindeel",
    "bgt:onbegroeidterreindeel": "onbegroeidterreindeel",
    "bgt:kunstwerkdeel": "kunstwerkdeel_vlak",
    "bgt:overigbouwwerk": "overigbouwwerk",
    "bgt:scheiding": "scheiding_vlak",
    "bgt:terrein": "onbegroeidterreindeel",  # terrein valt onder onbegroeide terreindelen
    "bgt:waterdeel": "waterdeel",
    "bgt:ondersteunendwaterdeel": "ondersteunendwaterdeel",
    "bgt:ondersteunendwegdeel": "ondersteunendwegdeel",
    "bgt:spoor": "spoor",
    "bgt:overbruggingsdeel": "overbruggingsdeel",
}

CRS_RD = "http://www.opengis.net/def/crs/EPSG/0/28992"


class BGTFetchError(RuntimeError):
    pass


def _resolve_layer(feature_type: str) -> str:
    """Zet WFS-typenaam of kale naam om naar OGC API laagnaam."""
    if feature_type in BGT_LAYER_ALIASES:
        return BGT_LAYER_ALIASES[feature_type]
    # Strip eventuele "bgt:" prefix
    return feature_type.removeprefix("bgt:")


def fetch_bgt(
    bbox: BBox,
    feature_type: str,
    *,
    max_features: int | None = None,
    endpoint: str = BGT_OGC_ENDPOINT,
) -> gpd.GeoDataFrame:
    """Haal alle features van ``feature_type`` op binnen ``bbox`` (sync).

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    feature_type
        BGT-laagnaam. Accepteert zowel WFS-stijl (``"bgt:pand"``) als
        kale naam (``"pand"``).
    max_features
        Optioneel maximum aantal features.
    endpoint
        OGC API root URL. Default: PDOK BGT OGC API.
    """
    validate_bbox(bbox, must_be_rd=True)
    layer = _resolve_layer(feature_type)
    session = http_session()

    minx, miny, maxx, maxy = bbox
    bbox_str = f"{minx},{miny},{maxx},{maxy}"

    frames: list[gpd.GeoDataFrame] = []
    fetched = 0

    # Eerste pagina-URL — PDOK OGC API accepteert geen 'offset' parameter;
    # paginatie verloopt uitsluitend via de 'next'-link in het antwoord.
    minx_i, miny_i, maxx_i, maxy_i = (int(c) for c in bbox)
    limit = OGC_PAGE_SIZE
    if max_features is not None:
        limit = min(OGC_PAGE_SIZE, max_features)
    next_url: str | None = (
        f"{endpoint}/collections/{layer}/items"
        f"?bbox={minx_i},{miny_i},{maxx_i},{maxy_i}"
        f"&bbox-crs={CRS_RD}&crs={CRS_RD}"
        f"&limit={limit}&f=json"
    )

    while next_url is not None:
        if max_features is not None and fetched >= max_features:
            break

        log.info("OGC API BGT %s fetched=%d url=%s", layer, fetched, next_url)
        resp = session.get(next_url, timeout=120, headers={"Accept": "application/geo+json"})

        if resp.status_code == 404:
            raise BGTFetchError(
                f"BGT laag '{layer}' niet gevonden op {endpoint}. "
                f"Controleer de laagnaam via {endpoint}/collections"
            )
        resp.raise_for_status()

        data = resp.json()
        features = data.get("features", [])
        if not features:
            break

        page = gpd.GeoDataFrame.from_features(features, crs="EPSG:28992")
        frames.append(page)
        fetched += len(features)

        next_url = next(
            (lnk["href"] for lnk in data.get("links", []) if lnk.get("rel") == "next"),
            None,
        )

    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

    gdf = gpd.GeoDataFrame(gpd.pd.concat(frames, ignore_index=True), crs="EPSG:28992")
    validate_rd_crs(gdf, strict=True)
    return gdf


async def async_fetch_bgt(
    bbox: BBox,
    feature_type: str,
    *,
    max_features: int | None = None,
    endpoint: str = BGT_OGC_ENDPOINT,
) -> gpd.GeoDataFrame:
    """Async variant van fetch_bgt — voor gebruik in orchestrator.gather()."""
    return await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: fetch_bgt(bbox, feature_type, max_features=max_features, endpoint=endpoint),
    )
