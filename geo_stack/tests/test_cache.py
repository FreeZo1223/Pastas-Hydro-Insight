"""Smoke-tests voor geo_stack.core.cache — inclusief thread-safety."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from geo_stack.core.cache import cached_fetch


def _make_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(100_000, 400_000, 110_000, 410_000)], crs="EPSG:28992"
    )


def test_cache_miss_then_hit(tmp_path):
    call_count = 0

    @cached_fetch(cache_dir=tmp_path, suffix=".parquet")
    def fetch(x: int) -> gpd.GeoDataFrame:
        nonlocal call_count
        call_count += 1
        return _make_gdf()

    result1 = fetch(1)
    assert call_count == 1
    assert isinstance(result1, gpd.GeoDataFrame)

    result2 = fetch(1)
    assert call_count == 1  # cache hit — geen tweede aanroep
    assert len(result2) == len(result1)


def test_cache_ttl_expired(tmp_path):
    call_count = 0

    @cached_fetch(cache_dir=tmp_path, suffix=".parquet", ttl_seconds=0.1)
    def fetch(x: int) -> gpd.GeoDataFrame:
        nonlocal call_count
        call_count += 1
        return _make_gdf()

    fetch(1)
    time.sleep(0.2)
    fetch(1)
    assert call_count == 2  # TTL verlopen → nieuwe aanroep


def test_cache_clear(tmp_path):
    @cached_fetch(cache_dir=tmp_path, suffix=".parquet")
    def fetch(x: int) -> gpd.GeoDataFrame:
        return _make_gdf()

    fetch(1)
    removed = fetch.clear_cache()
    assert removed >= 1
    assert not any(tmp_path.glob("fetch_*"))


def test_cache_thread_safety(tmp_path):
    """Parallelle writes naar dezelfde sleutel mogen niet crashen of corrupte files opleveren."""
    errors: list[Exception] = []

    @cached_fetch(cache_dir=tmp_path, suffix=".parquet")
    def fetch(x: int) -> gpd.GeoDataFrame:
        return _make_gdf()

    def worker():
        try:
            fetch(42)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety fouten: {errors}"
    cache_files = list(tmp_path.glob("fetch_*"))
    assert len(cache_files) == 1


def test_cache_different_args(tmp_path):
    call_count = 0

    @cached_fetch(cache_dir=tmp_path, suffix=".parquet")
    def fetch(x: int) -> gpd.GeoDataFrame:
        nonlocal call_count
        call_count += 1
        return _make_gdf()

    fetch(1)
    fetch(2)
    assert call_count == 2
