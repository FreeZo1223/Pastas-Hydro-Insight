"""Smoke-tests voor de persistentielaag."""

from __future__ import annotations

import sqlite3

import pytest

from pastasdash_v2.state import persistence as p


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Vervang het DB-pad door een tmp-file zodat tests elkaar niet beïnvloeden."""
    db = tmp_path / "state.db"
    monkeypatch.setattr(p, "STATE_DB_PATH", db)
    yield


def test_app_state_set_get_roundtrip():
    p.AppState.set("foo", {"bar": 42, "baz": [1, 2, 3]})
    assert p.AppState.get("foo") == {"bar": 42, "baz": [1, 2, 3]}


def test_app_state_default_when_missing():
    assert p.AppState.get("does_not_exist", default="fallback") == "fallback"


def test_app_state_delete():
    p.AppState.set("temp", "x")
    p.AppState.delete("temp")
    assert p.AppState.get("temp") is None


def test_ui_state_scoped_per_store():
    a = p.UIState("storeA")
    b = p.UIState("storeB")
    a.set("k", 1)
    b.set("k", 2)
    assert a.get("k") == 1
    assert b.get("k") == 2


def test_ui_state_all_and_clear():
    s = p.UIState("xx")
    s.set("a", 1)
    s.set("b", 2)
    assert s.all() == {"a": 1, "b": 2}
    s.clear()
    assert s.all() == {}
