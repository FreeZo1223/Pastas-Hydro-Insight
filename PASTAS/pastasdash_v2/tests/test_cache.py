"""Smoke-tests voor de memoize-decorator."""

from __future__ import annotations

import diskcache
import pytest

from pastasdash_v2.state import cache as c


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    fresh = diskcache.Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(c, "compute_cache", fresh)
    yield
    fresh.close()


def test_memoize_requires_store_key_first_arg():
    @c.memoize("ns")
    def f(store_key: str, x: int) -> int:
        return x * 2

    assert f("k", 3) == 6

    @c.memoize("ns2")
    def g(x: int) -> int:  # geen string als eerste arg
        return x

    with pytest.raises(TypeError):
        g(1)


def test_memoize_returns_cached_value():
    calls = {"n": 0}

    @c.memoize("hit")
    def f(store_key: str, x: int) -> int:
        calls["n"] += 1
        return x + 100

    assert f("k", 1) == 101
    assert f("k", 1) == 101
    assert calls["n"] == 1, "Tweede call had cached moeten zijn"


def test_invalidate_store_removes_only_matching():
    @c.memoize("ns")
    def f(store_key: str, x: int) -> int:
        return x

    f("storeA", 1)
    f("storeA", 2)
    f("storeB", 3)
    removed = c.invalidate_store("storeA")
    assert removed >= 2
    # storeB-key blijft bestaan
    keys = list(c.compute_cache.iterkeys())
    assert any(":storeB:" in k for k in keys)
