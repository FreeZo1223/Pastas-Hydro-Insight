"""Parallel fetch van meerdere datasets voor één AOI.

``fetch_bundle`` haalt alle gevraagde datasets concurrent op via
``asyncio.gather`` + ``run_in_executor``. Resultaten worden per dataset
gecachet; de bundle als geheel wordt gecachet als directory met per-dataset
Parquet-bestanden.

Gebruik::

    from geo_stack.bundle import fetch_bundle

    lagen = fetch_bundle(
        ["bgt", "bag_3d", "bro_bodemkaart"],
        bbox=(125_000, 460_000, 145_000, 480_000),
        feature_type="waterdeel",   # doorgegeven aan alle datasets
    )
    waterdelen = lagen["bgt"]
    panden_3d  = lagen["bag_3d"]
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import geopandas as gpd

from geo_stack.core.geo_utils import BBox

log = logging.getLogger(__name__)

_DEFAULT_BUNDLE_CACHE = Path("data/cache/bundles")


# ── Async kern ──────────────────────────────────────────────────────────────

async def _fetch_one(
    dataset: str,
    bbox: BBox,
    data_sources_yaml: Path | str | None,
    prefer_cloud_native: bool,
    **kw: Any,
) -> tuple[str, gpd.GeoDataFrame]:
    """Fetch één dataset in een thread-pool-executor (non-blocking)."""
    from geo_stack.fetch import fetch_features  # late import om circulaire deps te vermijden

    loop = asyncio.get_event_loop()
    try:
        gdf = await loop.run_in_executor(
            None,
            lambda: fetch_features(
                dataset,
                bbox,
                data_sources_yaml=data_sources_yaml,
                prefer_cloud_native=prefer_cloud_native,
                **kw,
            ),
        )
        log.info("Bundle: %s → %d features", dataset, len(gdf))
    except Exception as exc:  # noqa: BLE001
        log.warning("Bundle: %s faalde — lege GDF teruggegeven: %s", dataset, exc)
        gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
    return dataset, gdf


async def async_fetch_bundle(
    datasets: list[str],
    bbox: BBox,
    *,
    data_sources_yaml: Path | str | None = None,
    prefer_cloud_native: bool = True,
    **kw: Any,
) -> dict[str, gpd.GeoDataFrame]:
    """Haal meerdere datasets concurrent op.

    Parameters
    ----------
    datasets
        Lijst van dataset-sleutels zoals gedefinieerd in ``data_sources.yaml``.
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    data_sources_yaml
        Optioneel override-pad naar yaml.
    prefer_cloud_native
        Geef de voorkeur aan cloud-native backends.
    **kw
        Extra kwargs doorgegeven aan elk ``fetch_features``-call
        (bv. ``feature_type`` voor BGT).

    Returns
    -------
    dict[str, GeoDataFrame]
        ``{dataset_naam: GeoDataFrame}``. Datasets die falen produceren een
        lege GeoDataFrame (de rest wordt niet onderbroken).
    """
    tasks = [
        _fetch_one(ds, bbox, data_sources_yaml, prefer_cloud_native, **kw)
        for ds in datasets
    ]
    pairs = await asyncio.gather(*tasks)
    return dict(pairs)


# ── Sync wrapper met bundle-cache ───────────────────────────────────────────

def fetch_bundle(
    datasets: list[str],
    bbox: BBox,
    *,
    cache_dir: Path | str | None = None,
    ttl_seconds: float | None = None,
    data_sources_yaml: Path | str | None = None,
    prefer_cloud_native: bool = True,
    **kw: Any,
) -> dict[str, gpd.GeoDataFrame]:
    """Haal meerdere datasets parallel op, met optionele bundle-cache.

    Bij een cache-hit worden alle datasets ingeladen uit ``cache_dir``.
    Bij een miss worden datasets concurrent opgehaald en daarna gecachet.

    Parameters
    ----------
    datasets
        Lijst van dataset-sleutels (volgorde bepaalt de cache-hash niet).
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    cache_dir
        Map voor bundle-cache. ``None`` = ``data/cache/bundles``.
        Zet op een lege string (``""``) om cache uit te schakelen.
    ttl_seconds
        Cache-levensduur in seconden. ``None`` = onbeperkt.
    data_sources_yaml
        Optioneel override-pad naar yaml.
    prefer_cloud_native
        Geef de voorkeur aan cloud-native backends.
    **kw
        Extra kwargs doorgegeven aan elk ``fetch_features``-call.

    Returns
    -------
    dict[str, GeoDataFrame]
    """
    use_cache = cache_dir != ""
    bundle_dir: Path | None = None

    if use_cache:
        root = Path(cache_dir) if cache_dir else _DEFAULT_BUNDLE_CACHE
        bundle_hash = _bundle_hash(datasets, bbox, kw)
        bundle_dir = root / bundle_hash

        cached = _load_bundle_cache(bundle_dir, datasets, ttl_seconds)
        if cached is not None:
            log.info("Bundle cache HIT %s (%d datasets)", bundle_hash[:8], len(datasets))
            return cached

    t0 = time.monotonic()
    result = asyncio.run(
        async_fetch_bundle(
            datasets,
            bbox,
            data_sources_yaml=data_sources_yaml,
            prefer_cloud_native=prefer_cloud_native,
            **kw,
        )
    )
    elapsed = time.monotonic() - t0
    log.info(
        "Bundle opgehaald in %.1fs (%d datasets, %d features totaal)",
        elapsed,
        len(datasets),
        sum(len(gdf) for gdf in result.values()),
    )

    if use_cache and bundle_dir is not None:
        _save_bundle_cache(result, bundle_dir)

    return result


def list_bundle_cache(cache_dir: Path | str | None = None) -> list[dict]:
    """Toon gecachete bundles in ``cache_dir``.

    Returns
    -------
    list[dict]
        Gesorteerd op leeftijd (nieuwste eerst).
        Elk item heeft: ``hash``, ``datasets``, ``age_seconds``, ``size_kb``.
    """
    root = Path(cache_dir) if cache_dir else _DEFAULT_BUNDLE_CACHE
    if not root.exists():
        return []

    items = []
    for bundle_dir in root.iterdir():
        if not bundle_dir.is_dir():
            continue
        parquets = list(bundle_dir.glob("*.parquet"))
        if not parquets:
            continue
        meta_file = bundle_dir / "_meta.json"
        datasets: list[str] = []
        if meta_file.exists():
            try:
                datasets = json.loads(meta_file.read_text())["datasets"]
            except Exception:
                datasets = [p.stem for p in parquets]
        else:
            datasets = [p.stem for p in parquets]
        mtime = max(p.stat().st_mtime for p in parquets)
        size_kb = sum(p.stat().st_size for p in parquets) / 1024
        items.append({
            "hash": bundle_dir.name,
            "datasets": datasets,
            "age_seconds": time.time() - mtime,
            "size_kb": round(size_kb, 1),
        })

    return sorted(items, key=lambda x: x["age_seconds"])


# ── Helpers ─────────────────────────────────────────────────────────────────

def _bundle_hash(datasets: list[str], bbox: BBox, kw: dict) -> str:
    payload = json.dumps(
        {
            "datasets": sorted(datasets),
            "bbox": list(bbox),
            "kw": sorted(kw.items()),
        },
        default=str,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _load_bundle_cache(
    bundle_dir: Path,
    datasets: list[str],
    ttl: float | None,
) -> dict[str, gpd.GeoDataFrame] | None:
    if not bundle_dir.exists():
        return None
    parquets = {p.stem: p for p in bundle_dir.glob("*.parquet")}
    if set(datasets) != set(parquets.keys()):
        return None
    if ttl is not None:
        oldest = min(p.stat().st_mtime for p in parquets.values())
        if (time.time() - oldest) > ttl:
            return None
    return {name: gpd.read_parquet(path) for name, path in parquets.items()}


def _save_bundle_cache(result: dict[str, gpd.GeoDataFrame], bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for name, gdf in result.items():
        if not gdf.empty:
            gdf.to_parquet(bundle_dir / f"{name}.parquet", schema_version="1.1.0")
    meta = {"datasets": sorted(result.keys()), "saved_at": time.time()}
    (bundle_dir / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    log.info("Bundle gecachet in %s", bundle_dir)
