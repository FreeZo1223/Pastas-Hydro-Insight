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

    cloud_native_entry = next((e for e in entries if "cloud_native_url" in e), None)
    if prefer_cloud_native and cloud_native_entry is not None:
        cn_fn = _CLOUD_NATIVE_DISPATCH.get(dataset)
        if cn_fn is not None:
            try:
                log.info("Cloud-native fetch voor %s via %s", dataset, cn_fn.__name__)
                return cn_fn(bbox, **kwargs)
            except Exception as exc:
                log.warning(
                    "Cloud-native faalde voor %s: %s — val terug op directe fetcher",
                    dataset, exc,
                )
        else:
            log.debug(
                "Dataset %r heeft cloud_native_url maar geen mapping in "
                "_CLOUD_NATIVE_DISPATCH — val terug",
                dataset,
            )

    fallback_fn = _FALLBACK_DISPATCH.get(dataset)
    if fallback_fn is None:
        raise NoBackendAvailableError(
            f"Geen fallback fetcher voor {dataset!r}. "
            f"Mappings beschikbaar: {sorted(_FALLBACK_DISPATCH.keys())}"
        )
    log.info("Direct fetch voor %s via %s", dataset, fallback_fn.__name__)
    return fallback_fn(bbox, **kwargs)


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


def list_datasets(data_sources_yaml: Path | str | None = None) -> dict[str, dict[str, bool]]:
    """Toon per dataset welke backends beschikbaar zijn.

    Returns
    -------
    dict
        ``{dataset: {"cloud_native": bool, "fallback": bool}}``.
    """
    config = _load_data_sources(data_sources_yaml)
    out: dict[str, dict[str, bool]] = {}
    for dataset, entries in config.get("services", {}).items():
        has_cn_url = any("cloud_native_url" in e for e in entries)
        out[dataset] = {
            "cloud_native": has_cn_url and dataset in _CLOUD_NATIVE_DISPATCH,
            "fallback": dataset in _FALLBACK_DISPATCH,
        }
    return out
