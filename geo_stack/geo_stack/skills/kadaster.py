"""Kadaster — BRK percelen ophalen via PDOK Locatieserver.

Voorkeurmethode: REST API is sneller & betrouwbaarder dan WFS.
Zie CLAUDE.md voor details op CQL_FILTER-limitatie in tile-cached WFS.

Functie:
    fetch_parcels_by_kadastraal_id(ids, output_dir) → Path (GeoParquet)
    fetch_parcels_by_bbox(bbox, gemeente_akr) → GeoDataFrame
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely import wkt

from geo_stack.core.geo_utils import http_session, validate_bbox
from geo_stack.core.normalizer import normalize_to_geoparquet
from geo_stack.provenance import write_provenance
from geo_stack.report import FetchReport

log = logging.getLogger(__name__)

LOCATIESERVER_SEARCH = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
LOCATIESERVER_LOOKUP = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/lookup"

# AKR-codes kadastrale gemeenten (zie CLAUDE.md)
AKR_CODES = {
    "Lelystad": "LLS00",
    "Dronten": "DTN01",
    "Flevoland": ["LLS00", "DTN01"],  # subset
}


class KadasterFetchError(Exception):
    """Perceel-ophaal fout."""


def fetch_parcels_by_kadastraal_id(
    ids: list[str], output_dir: Path | None = None, silent: bool = False
) -> Path | None:
    """Zet lijst van kadastrale aanduidingen om naar GeoParquet.

    Parameters
    ----------
    ids
        Lijst van kadastrale aanduidingen, bijv.
        ``["LLS00-B-10", "DTN01-A-5", ...]``. Format: ``Gemeente-Sectie-Nr``.
    output_dir
        Outputfolder. Default: ``Path.cwd() / "data"``.
    silent
        Onderdrukt rapport-print.

    Returns
    -------
    pathlib.Path
        Pad naar het `.parquet`-bestand (met `.provenance.json` sidecar).
        ``None`` als geen percelen gevonden.

    Raises
    ------
    KadasterFetchError
        Network-fout of parse-fout.
    """
    output_dir = Path(output_dir or Path.cwd() / "data")
    output_dir.mkdir(exist_ok=True, parents=True)
    output_path = output_dir / "kadaster_percelen.parquet"

    features = []
    session = http_session()
    session.headers.update({"User-Agent": "geo_stack/1.0"})

    with FetchReport(
        "kadaster percelen",
        source=LOCATIESERVER_LOOKUP,
        cache_hit=False,
        silent=silent,
    ) as report:
        for i, kadastraal_id in enumerate(ids):
            try:
                # Zoek perceel-ID
                search_resp = session.get(
                    LOCATIESERVER_SEARCH,
                    params={
                        "q": kadastraal_id,
                        "fq": "type:perceel",
                        "rows": "1",
                    },
                    timeout=10,
                )
                search_resp.raise_for_status()
                docs = search_resp.json()["response"]["docs"]

                if not docs:
                    log.warning(
                        "%s — niet gevonden (vervallen of typo?)", kadastraal_id
                    )
                    continue

                doc_id = docs[0]["id"]

                # Haal volledige geometrie op
                lookup_resp = session.get(
                    LOCATIESERVER_LOOKUP,
                    params={"id": doc_id, "fl": "*"},
                    timeout=10,
                )
                lookup_resp.raise_for_status()
                doc = lookup_resp.json()["response"]["docs"][0]

                # Parse WKT geometrie (EPSG:28992)
                geom_wkt = doc.get("geometrie_rd")
                if not geom_wkt:
                    log.warning("%s — geen geometrie", kadastraal_id)
                    continue

                geometry = wkt.loads(geom_wkt)

                features.append(
                    {
                        "kadastraal_id": kadastraal_id,
                        "doc_id": doc_id,
                        "oppervlakte_m2": doc.get("kadastrale_grootte"),
                        "gemeente": doc.get("gemeentenaam"),
                        "geometry": geometry,
                    }
                )

            except requests.RequestException as exc:
                log.error("%s — network error: %s", kadastraal_id, exc)
                continue
            except (KeyError, ValueError) as exc:
                log.error("%s — parse error: %s", kadastraal_id, exc)
                continue

        # Rapport
        if not features:
            log.warning("Geen percelen gevonden in locatieserver")
            report.add("Status", "Geen resultaten")
            return None

        gdf = gpd.GeoDataFrame(features, geometry="geometry", crs="EPSG:28992")

        # Normaliseer naar GeoParquet
        result = normalize_to_geoparquet(
            gdf,
            output_path,
            reproject=False,
            drop_invalid=True,
            snake_case_columns=True,
        )

        report.finish(output_path)
        report.add("Gevonden percelen", len(features))
        if "oppervlakte_m2" in gdf.columns:
            total_ha = gdf["oppervlakte_m2"].sum() / 10_000
            report.add("Totale oppervlakte", f"{total_ha:.2f} ha")

        # Sidecar
        write_provenance(
            output_path,
            source=LOCATIESERVER_LOOKUP,
            params={"kadastraal_ids": ids, "count": len(ids)},
            feature_count=len(features),
            source_version="PDOK DKK (vorige kalenderdag)",
            extra={
                "input_count": len(ids),
                "not_found_count": len(ids) - len(features),
            },
        )

    return output_path


def fetch_parcels_by_bbox(
    bbox: tuple[float, float, float, float],
    gemeente_akr: str,
    crs_out: str = "EPSG:28992",
) -> gpd.GeoDataFrame:
    """Haal alle percelen op via BBOX (fallback als locatieserver niet volstaat).

    ⚠️  WFS is tile-cached, CQL_FILTER werkt niet. Download via BBOX en filter lokaal.

    Parameters
    ----------
    bbox
        BBOX (EPSG:28992): ``(minx, miny, maxx, maxy)``.
    gemeente_akr
        Kadastrale gemeentecode, bijv. ``"LLS00"`` (Lelystad) of ``"DTN01"`` (Dronten).
    crs_out
        Output CRS. Default: EPSG:28992.

    Returns
    -------
    geopandas.GeoDataFrame
        Alle percelen in de BBOX.

    Raises
    ------
    KadasterFetchError
        Network-fout of BBOX-limiet overschreden.
    """
    validate_bbox(bbox, must_be_rd=True)

    endpoint = "https://service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0"
    minx, miny, maxx, maxy = bbox

    # WFS GetFeature request
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "Kadaster:perceel",
        "outputFormat": "application/json",
        "srsName": "EPSG:28992",
        "bbox": f"{minx},{miny},{maxx},{maxy},urn:ogc:def:crs:EPSG::28992",
    }

    session = http_session()

    with FetchReport("kadaster BBOX", bbox=bbox, source=endpoint) as report:
        try:
            resp = session.get(endpoint, params=params, timeout=30)
            resp.raise_for_status()

            # pyogrio voor snellere parse
            import io

            import pyogrio

            gdf = pyogrio.read_dataframe(io.BytesIO(resp.content))

        except requests.RequestException as exc:
            raise KadasterFetchError(f"WFS fout: {exc}") from exc

        # Filter op gemeente-AKR
        if "AKRKadastraleGemeenteCodeWaarde" in gdf.columns:
            gdf = gdf[gdf["AKRKadastraleGemeenteCodeWaarde"] == gemeente_akr]

        # Verwijder vervallen percelen (statusHistorieCode != "G" = geen geschiedenis)
        if "statusHistorieCode" in gdf.columns:
            gdf = gdf[gdf["statusHistorieCode"] == "G"]

        if gdf.empty:
            log.warning("Geen percelen in BBOX na filtering")
            return gdf

        gdf = gdf.to_crs(crs_out)
        report.finish(gdf)

    return gdf
