"""locatieserver — Geocode adressen, plaatsnamen, BAG-objecten via PDOK.

PDOK Locatieserver REST API: zoek vrij op tekst en haal locatie
(RD + WGS84) op. Geen API-key vereist. Bron-versie volgt DKK + BAG
(vorige kalenderdag).

Functie:
    geocode(query, type=None, rows=10, full_geometry=False) -> GeoDataFrame
        Vrije zoekactie. Retourneert centroides (snel, één HTTP request).
        full_geometry=True doet extra lookup per id voor volledige polygon.

Ondersteunde types (filter): adres, gemeente, woonplaats, weg, postcode,
perceel, hectometer, buurt, wijk, waterschapsgebied, provincie, appartement.

Uncertainty visibility:
    De Locatieserver geeft per resultaat een ``score`` (relevantie, ~0-25).
    Lage scores en/of weergavenamen die fundamenteel afwijken van ``query``
    indiceren onzekerheid — gebruik dit veld in downstream UI.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import requests
from shapely import wkt

from geo_stack.core.geo_utils import http_session, validate_rd_crs

log = logging.getLogger(__name__)

LOCATIESERVER_BASE = "https://api.pdok.nl/bzk/locatieserver/search/v3_1"
LOCATIESERVER_SEARCH = f"{LOCATIESERVER_BASE}/free"
LOCATIESERVER_LOOKUP = f"{LOCATIESERVER_BASE}/lookup"

VALID_TYPES: frozenset[str] = frozenset({
    "adres", "gemeente", "woonplaats", "weg", "postcode", "perceel",
    "hectometer", "buurt", "wijk", "waterschapsgebied", "provincie",
    "appartement",
})

MAX_ROWS = 100

# Velden die we (indien aanwezig) overnemen uit de Locatieserver-respons.
# Type-specifiek — niet elk veld bestaat voor elk doc type.
_ATTRIBUTE_FIELDS: tuple[str, ...] = (
    "id", "type", "weergavenaam", "score", "bron",
    "gemeentenaam", "provincienaam", "woonplaatsnaam",
    "straatnaam", "huisnummer", "huisletter", "huisnummertoevoeging",
    "postcode", "buurtnaam", "wijknaam",
    "waterschapsnaam", "kadastrale_grootte",
)


class LocalisatieFetchError(RuntimeError):
    """Fout bij ophalen van locatie via PDOK Locatieserver."""


def geocode(
    query: str,
    type: str | None = None,
    rows: int = 10,
    full_geometry: bool = False,
) -> gpd.GeoDataFrame:
    """Zoek adressen, plaatsen of BAG/BRK-objecten via PDOK Locatieserver.

    Parameters
    ----------
    query
        Zoektekst. Voorbeelden:
        ``"Lange Voorhout 8 Den Haag"`` (adres),
        ``"Lelystad"`` (plaats/gemeente),
        ``"LLS00-B-10"`` (kadastrale aanduiding).
    type
        Optioneel filter op resultaattype (zie ``VALID_TYPES``).
        ``None`` = alle types in één respons.
    rows
        Aantal resultaten (1..100). Default 10. PDOK staat max 100 toe.
    full_geometry
        ``True`` = extra lookup-call per id om polygon op te halen
        (voor perceel, buurt, wijk, gemeente). Trager (N+1 requests).
        ``False`` = alleen centroide (default, één request).

    Returns
    -------
    geopandas.GeoDataFrame
        CRS = EPSG:28992. Kolommen:
        ``id, type, weergavenaam, score, bron, geometry``, plus
        type-specifieke velden (``gemeentenaam``, ``straatnaam``,
        ``huisnummer``, ``postcode``, …) waar aanwezig.

        Lege GeoDataFrame (met juiste CRS) als geen resultaten.

    Raises
    ------
    LocalisatieFetchError
        Bij netwerk-fout, ongeldig type, ongeldig aantal rows, of
        onparsebare JSON-respons.
    """
    if rows < 1 or rows > MAX_ROWS:
        raise LocalisatieFetchError(
            f"rows moet tussen 1 en {MAX_ROWS} liggen, kreeg {rows}"
        )
    if type is not None and type not in VALID_TYPES:
        raise LocalisatieFetchError(
            f"Onbekend type {type!r}. Geldige types: {sorted(VALID_TYPES)}"
        )

    session = http_session()
    params: dict[str, str] = {"q": query, "rows": str(rows)}
    if type is not None:
        params["fq"] = f"type:{type}"

    log.info("Locatieserver search: q=%r type=%s rows=%d", query, type, rows)

    try:
        resp = session.get(LOCATIESERVER_SEARCH, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise LocalisatieFetchError(f"Locatieserver fetch mislukt: {exc}") from exc
    except ValueError as exc:
        raise LocalisatieFetchError(f"Locatieserver JSON parse error: {exc}") from exc

    docs = data.get("response", {}).get("docs", [])
    if not docs:
        log.info("Locatieserver: geen resultaten voor q=%r type=%s", query, type)
        return _empty_gdf()

    records: list[dict[str, Any]] = []
    for doc in docs:
        rec = _parse_doc(doc)
        if rec is not None:
            records.append(rec)

    if not records:
        log.warning(
            "Locatieserver: %d docs ontvangen maar geen geldige geometrie", len(docs)
        )
        return _empty_gdf()

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:28992")

    if full_geometry:
        gdf = _enrich_with_full_geometry(gdf, session)

    validate_rd_crs(gdf, strict=True)
    return gdf


# ---------------------------------------------------------------------------
# Privé helpers
# ---------------------------------------------------------------------------


def _empty_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")


def _parse_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Extract relevant velden + parse RD-geometrie WKT naar shapely."""
    geom_wkt = doc.get("centroide_rd") or doc.get("geometrie_rd")
    if not geom_wkt:
        return None
    try:
        geometry = wkt.loads(geom_wkt)
    except Exception as exc:
        log.warning(
            "Geometrie parse mislukt voor id=%s: %s", doc.get("id"), exc
        )
        return None

    rec: dict[str, Any] = {field: doc.get(field) for field in _ATTRIBUTE_FIELDS}
    rec["geometry"] = geometry
    return rec


def _enrich_with_full_geometry(
    gdf: gpd.GeoDataFrame, session: requests.Session
) -> gpd.GeoDataFrame:
    """Vervang centroides door volledige polygonen via lookup-endpoint."""
    new_geoms = list(gdf.geometry)
    for i, doc_id in enumerate(gdf["id"]):
        if doc_id is None:
            continue
        try:
            resp = session.get(
                LOCATIESERVER_LOOKUP,
                params={"id": doc_id, "fl": "geometrie_rd"},
                timeout=15,
            )
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
            if docs and docs[0].get("geometrie_rd"):
                new_geoms[i] = wkt.loads(docs[0]["geometrie_rd"])
        except Exception as exc:
            log.warning("Lookup mislukt voor id=%s: %s", doc_id, exc)

    result = gdf.copy()
    result["geometry"] = gpd.GeoSeries(new_geoms, crs="EPSG:28992")
    return result
