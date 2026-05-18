"""Disk-cache voor geo_stack fetch-functies.

Decorator ``@cached_fetch`` hashed (functienaam, args, kwargs) naar een
bestandsnaam in een configureerbare cache-dir. Bij cache-hit wordt het
eerder opgeslagen GeoParquet of pad naar GeoTIFF teruggegeven.

Thread-safe: writes gebruiken atomic rename via tempfile zodat parallelle
agents nooit een half-geschreven bestand inlezen.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path("data/cache")

# Per-key locks so simultaneous writers to the same cache key don't race
# on os.replace(). Windows is stricter than POSIX about replacing a file
# while another handle is open.
_KEY_LOCKS: dict[str, threading.Lock] = {}
_KEY_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _KEY_LOCKS_GUARD:
        lock = _KEY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[key] = lock
        return lock


def cached_fetch(
    *,
    cache_dir: Path | str = _DEFAULT_CACHE_DIR,
    suffix: str = ".parquet",
    ttl_seconds: float | None = None,
) -> Callable:
    """Decorator die een fetch-functie omhult met een disk-cache.

    Thread-safe via atomic rename: schrijft naar een tempbestand in dezelfde
    map en hernoemt atomisch. Op Windows is os.replace() niet altijd echt
    atomisch, maar voorkomt wel half-geschreven bestanden.
    """
    cache_dir = Path(cache_dir)

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(fn.__name__, args, kwargs)
            cache_path = cache_dir / f"{fn.__name__}_{key}{suffix}"

            if _is_valid(cache_path, ttl_seconds):
                age = time.time() - cache_path.stat().st_mtime
                size_kb = cache_path.stat().st_size / 1024
                log.info(
                    "CACHE HIT  %s @ %s (%.0f KB, %.1fs geleden)",
                    fn.__name__, key, size_kb, age,
                )
                return _load(cache_path, suffix)

            # Serialise writers for the same key so os.replace() doesn't
            # collide on Windows. After acquiring the lock we re-check
            # the cache: an earlier writer may have just produced it.
            with _lock_for(str(cache_path)):
                if _is_valid(cache_path, ttl_seconds):
                    log.info("CACHE HIT (na lock) %s @ %s", fn.__name__, key)
                    return _load(cache_path, suffix)

                log.info("CACHE MISS %s @ %s — ophalen...", fn.__name__, key)
                result = fn(*args, **kwargs)
                cache_dir.mkdir(parents=True, exist_ok=True)
                _save_atomic(result, cache_path, suffix)
                return result

        wrapper.cache_dir = cache_dir  # type: ignore[attr-defined]
        wrapper.clear_cache = lambda: _clear_prefix(  # type: ignore[attr-defined]
            cache_dir, fn.__name__
        )
        return wrapper

    return decorator


def _make_key(fn_name: str, args: tuple, kwargs: dict) -> str:
    payload = json.dumps(
        {"fn": fn_name, "args": list(args), "kwargs": sorted(kwargs.items())},
        default=str,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def _is_valid(path: Path, ttl: float | None) -> bool:
    if not path.exists():
        return False
    if ttl is not None:
        age = time.time() - path.stat().st_mtime
        return age < ttl
    return True


def _load(path: Path, suffix: str) -> Any:
    if suffix == ".parquet":
        return gpd.read_parquet(path)
    return path


def _save_atomic(result: Any, target: Path, suffix: str) -> None:
    """Schrijf naar tempbestand, hernoem atomisch naar target."""
    target.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".parquet" and isinstance(result, gpd.GeoDataFrame):
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        os.close(fd)
        try:
            result.to_parquet(tmp, schema_version="1.1.0")
            os.replace(tmp, target)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    elif suffix == ".tif" and isinstance(result, Path) and result.exists():
        import shutil
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp.tif")
        os.close(fd)
        try:
            shutil.copy2(result, tmp)
            os.replace(tmp, target)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    else:
        log.warning(
            "Cache-opslag niet ondersteund voor type %s (suffix=%s); sla over",
            type(result).__name__, suffix,
        )


def _clear_prefix(cache_dir: Path, prefix: str) -> int:
    """Verwijder alle cache-bestanden die beginnen met ``prefix``."""
    removed = 0
    for f in cache_dir.glob(f"{prefix}_*"):
        f.unlink()
        removed += 1
    log.info("Cache gewist: %d bestanden voor prefix '%s'", removed, prefix)
    return removed
