"""Smart fetch-dispatcher — probeert eerst cloud-native streaming.

Eén entrypoint voor downstream callers. Routet automatisch naar de snelste
beschikbare backend per dataset:

1. Als ``data_sources.yaml`` een ``cloud_native_url`` heeft voor de dataset
   → probeer DuckDB-streaming via ``geo_stack.skills.cloud_native``.
2. Als cloud-native faalt of niet bestaat → val terug op de directe fetcher
   (WFS/REST/WCS van de skill).

Gebruik:

    from geo_stack.fetch import fetch_features

    panden = fetch_features("bag_3d", bbox=(125_000, 460_000, 145_000, 480_000))
    bgt = fetch_features("bgt", bbox=..., feature_type="bgt:pand")

Filosofie: downstream (BKN, SMP, LESA-v2) kent geen URLs en geen verschil
tussen WFS en cloud-native. Het routeer-besluit zit in deze module.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import yaml

from geo_stack.core.geo_utils import BBox, validate_bbox
from geo_stack.drivers import DRIVERS

log = logging.getLogger(__name__)

DEFAULT_DATA_SOURCES = Path(
    os.environ.get(
        "GEO_STACK_DATA_SOURCES",
        str(Path(__file__).parent.parent / "data_sources.yaml"),
    )
)


class UnknownDatasetError(KeyError):
    """Dataset-naam staat niet in data_sources.yaml en heeft geen fallback."""


class NoBackendAvailableError(RuntimeError):
    """Geen werkende backend gevonden voor deze dataset."""


def fetch_features(
    dataset: str,
    bbox: BBox,
    *,
    data_sources_yaml: Path | str | None = None,
    prefer_cloud_native: bool = True,
    **kwargs: Any,
) -> gpd.GeoDataFrame:
    """Smart-fetch features. Probeert eerst cloud-native, valt terug op directe fetcher.

    Parameters
    ----------
    dataset
        Sleutel in ``data_sources.yaml`` (bv. ``"bag_3d"``, ``"bgt"``, ``"kadaster"``).
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    data_sources_yaml
        Override-pad naar yaml. ``None`` = gebruik ingebakken
        ``geo_stack/data_sources.yaml``.
    prefer_cloud_native
        Default ``True``. Zet op ``False`` om cloud-native over te slaan
        (bv. voor debugging van de WFS-route).
    **kwargs
        Doorgegeven aan de uiteindelijke fetcher (bv. ``feature_type`` voor BGT,
        ``layer`` voor 3DBAG).

    Returns
    -------
    gpd.GeoDataFrame
        Features in EPSG:28992.

    Raises
    ------
    UnknownDatasetError
        Dataset niet bekend.
    NoBackendAvailableError
        Cloud-native én fallback faalden.
    """
    validate_bbox(bbox, must_be_rd=True)
    config = _load_data_sources(data_sources_yaml)
    entries = config.get("services", {}).get(dataset)
    if not entries:
        raise UnknownDatasetError(
            f"Dataset {dataset!r} niet in data_sources.yaml. "
            f"Beschikbaar: {sorted(config.get('services', {}).keys())}"
        )

    # ── Legacy-dispatch (backward compat) ──────────────────────────────────
    # Oudere tests en callers patchen _CLOUD_NATIVE_DISPATCH / _FALLBACK_DISPATCH.
    # Als daar een mapping voor deze dataset bestaat, respecteren we die nog.
    legacy = _try_legacy_dispatch(
        dataset, bbox, entries, prefer_cloud_native, **kwargs
    )
    if legacy is not None:
        return legacy

    # ── Driver-dispatch (data_sources.yaml-gedreven) ───────────────────────
    # Sorteer entries: cloud-native eerst als prefer_cloud_native, dan op
    # volgorde in de yaml. Probeer per entry de bijbehorende driver; faalt er
    # een, dan log + probeer de volgende.
    ordered = _order_entries(entries, prefer_cloud_native)
    errors: list[str] = []
    for entry in ordered:
        service_type = entry.get("service_type")
        driver_cls = DRIVERS.get(service_type)
        if driver_cls is None:
            errors.append(
                f"{entry.get('label', '?')}: geen driver voor service_type={service_type!r}"
            )
            continue
        try:
            log.info(
                "Fetch %s via %s (%s)",
                dataset, driver_cls.__name__, entry.get("label", "?"),
            )
            return driver_cls(entry).fetch(bbox, **kwargs)
        except Exception as exc:  # noqa: BLE001 — bewust: val terug op volgende entry
            msg = f"{entry.get('label', '?')} ({service_type}): {exc}"
            log.warning("Driver faalde voor %s — %s; probeer volgende entry", dataset, msg)
            errors.append(msg)

    raise NoBackendAvailableError(
        f"Geen werkende backend voor {dataset!r}. Geprobeerd:\n  "
        + "\n  ".join(errors)
    )


def _order_entries(entries: list[dict], prefer_cloud_native: bool) -> list[dict]:
    """Sorteer entries; zet CLOUD_NATIVE vooraan als ``prefer_cloud_native``.

    Drivers zonder mapping in ``DRIVERS`` blijven in de lijst maar worden
    tijdens dispatch overgeslagen (met een nette foutmelding).
    """
    if not prefer_cloud_native:
        return [e for e in entries if e.get("service_type") != "CLOUD_NATIVE"] + [
            e for e in entries if e.get("service_type") == "CLOUD_NATIVE"
        ]
    cloud = [e for e in entries if e.get("service_type") == "CLOUD_NATIVE"]
    rest = [e for e in entries if e.get("service_type") != "CLOUD_NATIVE"]
    return cloud + rest


def _try_legacy_dispatch(
    dataset: str,
    bbox: BBox,
    entries: list[dict],
    prefer_cloud_native: bool,
    **kwargs: Any,
) -> gpd.GeoDataFrame | None:
    """Respecteer handmatig gepatchte legacy-dispatch-dicts (backward compat).

    Returnt ``None`` als er geen legacy-mapping is, zodat de driver-dispatch
    het overneemt. Gooit ``NoBackendAvailableError`` als een legacy cloud-native
    faalt én er geen legacy-fallback is (oud gedrag van de tests).
    """
    has_cn_url = any("cloud_native_url" in e for e in entries)
    cn_fn = _CLOUD_NATIVE_DISPATCH.get(dataset)
    fb_fn = _FALLBACK_DISPATCH.get(dataset)

    if cn_fn is None and fb_fn is None:
        return None  # geen legacy-mapping → moderne driver-dispatch

    if prefer_cloud_native and has_cn_url and cn_fn is not None:
        try:
            log.info("Legacy cloud-native fetch voor %s via %s", dataset, cn_fn.__name__)
            return cn_fn(bbox, **kwargs)
        except Exception as exc:
            log.warning("Legacy cloud-native faalde voor %s: %s", dataset, exc)
            if fb_fn is None:
                raise NoBackendAvailableError(
                    f"Cloud-native faalde voor {dataset!r} en geen fallback."
                ) from exc

    if fb_fn is not None:
        log.info("Legacy direct fetch voor %s via %s", dataset, fb_fn.__name__)
        return fb_fn(bbox, **kwargs)

    return None


def _load_data_sources(path: Path | str | None) -> dict[str, Any]:
    yaml_path = Path(path) if path else DEFAULT_DATA_SOURCES
    if not yaml_path.exists():
        raise FileNotFoundError(f"data_sources.yaml niet gevonden: {yaml_path}")
    with yaml_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Dispatch-mappings ──────────────────────────────────────────────────────
# Lazy imports zodat een gebruiker zonder duckdb of earthengine-api de
# dispatcher nog kan gebruiken voor dataset-mappings die geen extras nodig hebben.

def _bag_3d_cloud_native(bbox: BBox, *, layer: str = "lod22_2d", **kw: Any) -> gpd.GeoDataFrame:
    from geo_stack.skills.cloud_native import stream_3dbag
    return stream_3dbag(bbox=bbox, layer=layer, **kw)


def _bag_cloud_native(bbox: BBox, *, layer: str = "pand", **kw: Any) -> gpd.GeoDataFrame:
    from geo_stack.skills.cloud_native import stream_bag_extract
    return stream_bag_extract(bbox=bbox, layer=layer, **kw)


def _bgt_fallback(bbox: BBox, *, feature_type: str = "bgt:pand", **kw: Any) -> gpd.GeoDataFrame:
    from geo_stack.skills.bgt import fetch_bgt
    return fetch_bgt(bbox=bbox, feature_type=feature_type, **kw)


def _kadaster_fallback(bbox: BBox, **kw: Any) -> gpd.GeoDataFrame:
    from geo_stack.skills.kadaster import fetch_parcels_by_bbox
    return fetch_parcels_by_bbox(bbox=bbox, **kw)


_CLOUD_NATIVE_DISPATCH: dict[str, Callable[..., gpd.GeoDataFrame]] = {
    "bag_3d": _bag_3d_cloud_native,
    "bag": _bag_cloud_native,
}

_FALLBACK_DISPATCH: dict[str, Callable[..., gpd.GeoDataFrame]] = {
    "bgt": _bgt_fallback,
    "kadaster": _kadaster_fallback,
    # bag_3d / bag fallback bestaat niet — die hebben alleen cloud-native pad
}


def list_datasets(data_sources_yaml: Path | str | None = None) -> dict[str, dict]:
    """Toon per dataset welke backends beschikbaar zijn.

    Returns
    -------
    dict
        ``{dataset: {"cloud_native": bool, "fallback": bool, "driver": str|None}}``.
        ``driver`` is de service_type-string waarvoor een driver-klasse bestaat,
        of ``None`` als alleen legacy-dispatch of geen backend beschikbaar is.
    """
    config = _load_data_sources(data_sources_yaml)
    out: dict[str, dict] = {}
    for dataset, entries in config.get("services", {}).items():
        has_cn_url = any("cloud_native_url" in e for e in entries)
        service_types = [e.get("service_type") for e in entries]
        driver_type = next((st for st in service_types if st in DRIVERS), None)
        out[dataset] = {
            "cloud_native": has_cn_url and (
                dataset in _CLOUD_NATIVE_DISPATCH or "CLOUD_NATIVE" in service_types
            ),
            "fallback": dataset in _FALLBACK_DISPATCH or any(
                st in DRIVERS for st in service_types if st != "CLOUD_NATIVE"
            ),
            "driver": driver_type,
        }
    return out
