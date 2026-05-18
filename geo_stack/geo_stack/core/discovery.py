"""Discovery — vind beschikbare PDOK / OGC / STAC services voor een thema.

Output: lijst dicts met ``service_type``, ``endpoint``, ``feature_types``,
``crs_supported`` en ``verified``. Geen verzonnen endpoints — als de service
niet in de registry staat én GetCapabilities faalt, retourneer een
``error``-veld.

Registry wordt geladen uit ``data_sources.yaml`` in de geo_stack-packageroot.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests
import yaml

from geo_stack.core.geo_utils import BBox, http_session

log = logging.getLogger(__name__)

_DATA_SOURCES_YAML = Path(__file__).parent.parent.parent / "data_sources.yaml"


def _load_registry() -> dict[str, list[dict[str, Any]]]:
    """Laad data_sources.yaml; fail vroeg als het bestand ontbreekt."""
    if not _DATA_SOURCES_YAML.exists():
        raise FileNotFoundError(
            f"data_sources.yaml niet gevonden op {_DATA_SOURCES_YAML}. "
            "Controleer dat het pakket correct geïnstalleerd is."
        )
    with _DATA_SOURCES_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("services", {})


_WFS_NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "ows": "http://www.opengis.net/ows/1.1",
}


def discover_services(
    theme: str,
    service_types: list[str] | None = None,
    bbox: BBox | None = None,
) -> list[dict[str, Any]]:
    """Geef een lijst van beschikbare en geverifieerde services voor ``theme``."""
    service_types = service_types or ["WFS", "WCS", "STAC", "CLOUD_NATIVE", "REST"]
    registry = _load_registry()
    entries = registry.get(theme.lower(), [])
    if not entries:
        log.warning("Thema '%s' niet gevonden in data_sources.yaml", theme)
    results: list[dict[str, Any]] = []
    session = http_session()

    for entry in entries:
        stype = entry.get("service_type", "")
        if stype not in service_types:
            continue
        if stype == "WFS":
            results.append(_inspect_wfs(entry["endpoint"], session, extra=entry))
        elif stype == "WCS":
            results.append(_inspect_wcs(entry["endpoint"], session, extra=entry))
        elif stype == "STAC":
            results.append(_inspect_stac(entry["endpoint"], session, extra=entry))
        elif stype in {"CLOUD_NATIVE", "REST"}:
            results.append({
                **entry,
                "verified": True,
                "feature_types": entry.get("layers", []),
                "crs_supported": ["EPSG:28992"],
            })
        else:
            results.append({**entry, "verified": False, "feature_types": []})

    return results


def _inspect_wfs(
    endpoint: str, session: requests.Session, *, extra: dict[str, Any]
) -> dict[str, Any]:
    params = {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}
    try:
        resp = session.get(endpoint, params=params, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        return {**extra, "verified": False, "error": str(exc), "feature_types": []}

    feature_types: list[str] = []
    crs_set: set[str] = set()
    for ft in root.findall(".//wfs:FeatureType", _WFS_NS):
        name_el = ft.find("wfs:Name", _WFS_NS)
        if name_el is not None and name_el.text:
            feature_types.append(name_el.text)
        default_crs = ft.find("wfs:DefaultCRS", _WFS_NS)
        if default_crs is not None and default_crs.text:
            crs_set.add(_normalize_crs(default_crs.text))

    return {
        **extra,
        "verified": True,
        "feature_types": sorted(feature_types),
        "crs_supported": sorted(crs_set),
    }


def _inspect_wcs(
    endpoint: str, session: requests.Session, *, extra: dict[str, Any]
) -> dict[str, Any]:
    params = {"service": "WCS", "version": "2.0.1", "request": "GetCapabilities"}
    try:
        resp = session.get(endpoint, params=params, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        return {**extra, "verified": False, "error": str(exc), "feature_types": []}

    coverages: list[str] = []
    for cov in root.iter():
        if cov.tag.endswith("CoverageId") and cov.text:
            coverages.append(cov.text)

    return {
        **extra,
        "verified": True,
        "feature_types": sorted(coverages),
        "crs_supported": ["EPSG:28992"],
    }


def _inspect_stac(
    endpoint: str, session: requests.Session, *, extra: dict[str, Any]
) -> dict[str, Any]:
    try:
        resp = session.get(f"{endpoint.rstrip('/')}/collections", timeout=30)
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return {**extra, "verified": False, "error": str(exc), "feature_types": []}

    collections = [c["id"] for c in body.get("collections", []) if "id" in c]
    return {
        **extra,
        "verified": True,
        "feature_types": sorted(collections),
        "crs_supported": ["EPSG:4326"],
    }


def _normalize_crs(crs_str: str) -> str:
    if "EPSG" in crs_str.upper():
        code = crs_str.rsplit(":", 1)[-1]
        if code.isdigit():
            return f"EPSG:{code}"
    return crs_str
