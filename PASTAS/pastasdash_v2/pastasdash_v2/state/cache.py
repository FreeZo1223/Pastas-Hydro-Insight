"""Persistente compute-cache met diskcache.

Cache key bevat altijd ``store_key`` (canoniek pad of hash van de store),
zodat resultaten van verschillende PastaStores nooit colliden. Memoize-
decorator is bedoeld voor zware functies (model-fit, stats, plots) die
deterministische output geven voor dezelfde input.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
from typing import Any, Callable, TypeVar

import diskcache

from pastasdash_v2.config import COMPUTE_CACHE_DIR

log = logging.getLogger(__name__)

T = TypeVar("T")

compute_cache: diskcache.Cache = diskcache.Cache(
    str(COMPUTE_CACHE_DIR), size_limit=int(2e9)  # 2 GB
)


def _stable_key(args: tuple, kwargs: dict, signature: inspect.Signature) -> str:
    """Maak een stabiele JSON-key uit alle gebonden argumenten."""
    try:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        payload = {k: _normalize(v) for k, v in bound.arguments.items()}
    except TypeError:
        payload = {"args": [_normalize(a) for a in args], "kwargs": {k: _normalize(v) for k, v in kwargs.items()}}
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


def _normalize(value: Any) -> Any:
    """Maak unhashbare/object-types reproduceerbaar JSON-serializable."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return value.tolist()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


def memoize(namespace: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: cache resultaat in ``compute_cache`` onder een namespace.

    De eerste argument van de gewrapte functie MOET een ``store_key`` zijn
    (string) — dat garandeert dat cache-entries per-store gescheiden zijn.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if not args or not isinstance(args[0], str):
                raise TypeError(
                    f"@memoize-decorator vereist dat eerste arg van {fn.__name__} "
                    "een store_key (str) is."
                )
            key = f"{namespace}:{args[0]}:{_stable_key(args[1:], kwargs, signature)}"
            try:
                hit = compute_cache.get(key, default=_MISS)
                if hit is not _MISS:
                    return hit  # type: ignore[return-value]
            except Exception as exc:  # noqa: BLE001
                log.warning("Cache read faalde voor %s: %s", key, exc)

            result = fn(*args, **kwargs)
            try:
                compute_cache.set(key, result)
            except Exception as exc:  # noqa: BLE001
                log.warning("Cache write faalde voor %s: %s", key, exc)
            return result

        wrapper.cache_key_fn = lambda *a, **kw: f"{namespace}:{a[0]}:{_stable_key(a[1:], kw, signature)}"  # type: ignore[attr-defined]
        return wrapper

    return decorator


_MISS = object()


def invalidate_store(store_key: str) -> int:
    """Verwijder alle cache-entries voor een specifieke store. Geeft aantal terug."""
    n = 0
    for key in list(compute_cache.iterkeys()):
        if f":{store_key}:" in key:
            compute_cache.delete(key)
            n += 1
    return n
