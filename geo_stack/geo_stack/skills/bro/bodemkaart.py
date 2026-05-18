"""BRO Bodemkaart 1:50.000 via PDOK WFS.

Vlakken met bodemtype-codes en omschrijvingen. Gebruikt voor LESA
rangorde-positie 3 (bodem). Geen CQL_FILTER — fetch via BBOX.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from geo_stack.core.geo_utils import BBox, validate_bbox

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger(__name__)

# Sinds eind 2025: BRO Bodemkaart wordt gehost door WUR/BIS Nederland,
# niet meer via PDOK. Endpoint en typename zijn gewijzigd.
BODEMKAART_ENDPOINT = "https://maps.bodemdata.nl/geoserver/wfs"
BODEMKAART_TYPENAME = "bodem:Bodemkaart50000_v2025"


class BROFetchError(RuntimeError):
    """Raised when a BRO fetch fails (network, schema, or empty response)."""


def fetch_bodemkaart(
    bbox: BBox,
    *,
    output_path: Path | str | None = None,
    endpoint: str = BODEMKAART_ENDPOINT,
    typename: str = BODEMKAART_TYPENAME,
    extra_buffer_m: float = 200.0,
) -> "gpd.GeoDataFrame":
    """Fetch BRO Bodemkaart 1:50.000 vlakken voor een BBOX (sync).

    Parameters
    ----------
    bbox
        (minx, miny, maxx, maxy) in EPSG:28992.
    extra_buffer_m
        Buffer rondom bbox in meters; bodemvlakken overspannen de grens.
    output_path
        Optioneel pad om resultaat als GeoPackage op te slaan.

    Raises
    ------
    BROFetchError
        Als de service down is of het typename niet meer geldig.
    """
    import geopandas as gpd  # noqa: WPS433 — lazy import

    validate_bbox(bbox, must_be_rd=True)
    minx, miny, maxx, maxy = bbox
    b = extra_buffer_m
    buf_bbox = (minx - b, miny - b, maxx + b, maxy + b)

    wfs_url = (
        f"{endpoint}?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeName={typename}&srsName=EPSG:28992"
        f"&bbox={buf_bbox[0]},{buf_bbox[1]},{buf_bbox[2]},{buf_bbox[3]},EPSG:28992"
        f"&outputFormat=application/json"
    )

    log.info("BRO Bodemkaart fetch: %s @ %s", typename, buf_bbox)
    try:
        gdf = gpd.read_file(wfs_url, engine="pyogrio")
    except Exception as exc:
        raise BROFetchError(
            f"BRO Bodemkaart fetch mislukt voor {typename} @ {endpoint}: {exc}\n"
            "Tip: check GetCapabilities op "
            f"{endpoint}?service=WFS&version=2.0.0&request=GetCapabilities"
        ) from exc

    if gdf.empty:
        log.warning("BRO Bodemkaart: geen features voor bbox %s", buf_bbox)
        return gdf

    if gdf.crs is None or gdf.crs.to_epsg() != 28992:
        gdf = gdf.to_crs("EPSG:28992")

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(out, driver="GPKG")
        log.info("Bodemkaart opgeslagen: %s (%d features)", out, len(gdf))

    return gdf


def get_bro_capabilities(endpoint: str) -> dict[str, Any]:
    """Fetch beschikbare WFS-lagen via GetCapabilities."""
    from geo_stack.core.geo_utils import http_session

    session = http_session()
    url = f"{endpoint}?service=WFS&version=2.0.0&request=GetCapabilities"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    typenames = re.findall(r"<Name>([^<]+)</Name>", resp.text)
    return {"endpoint": endpoint, "typenames": typenames, "raw_length": len(resp.text)}
