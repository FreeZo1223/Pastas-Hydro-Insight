"""SQLite-backed persistent state.

Twee tabellen:

- ``app_state``: globale key/value (laatste-store-pad, laatste tab, theme, ...)
- ``ui_state``: per-store UI-state (selecties, filters, datepickers, ...),
  gekey'd op ``store_key`` (meestal de canonieke pad-string).

Alle waarden worden JSON-geserialiseerd. Eén connectie per proces is
voldoende voor lokale single-user gebruik.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from pastasdash_v2.config import STATE_DB_PATH

log = logging.getLogger(__name__)

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ui_state (
    store_key TEXT NOT NULL,
    key       TEXT NOT NULL,
    value     TEXT NOT NULL,
    updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (store_key, key)
);
"""


def _connect(path: Path = STATE_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with _LOCK:
        c = _connect()
        try:
            yield c
        finally:
            c.close()


class AppState:
    """Globale app-state: laatste store, laatste tab, etc."""

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        with _conn() as c:
            row = c.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            log.warning("Corrupte app_state value voor %s; default teruggegeven.", key)
            return default

    @staticmethod
    def set(key: str, value: Any) -> None:
        payload = json.dumps(value, default=str)
        with _conn() as c:
            c.execute(
                "INSERT INTO app_state(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated=CURRENT_TIMESTAMP",
                (key, payload),
            )

    @staticmethod
    def delete(key: str) -> None:
        with _conn() as c:
            c.execute("DELETE FROM app_state WHERE key=?", (key,))


class UIState:
    """Per-store UI-state. ``store_key`` is meestal de canonieke pad-string."""

    def __init__(self, store_key: str) -> None:
        self.store_key = store_key

    def get(self, key: str, default: Any = None) -> Any:
        with _conn() as c:
            row = c.execute(
                "SELECT value FROM ui_state WHERE store_key=? AND key=?",
                (self.store_key, key),
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, default=str)
        with _conn() as c:
            c.execute(
                "INSERT INTO ui_state(store_key,key,value) VALUES(?,?,?) "
                "ON CONFLICT(store_key,key) DO UPDATE SET value=excluded.value, "
                "updated=CURRENT_TIMESTAMP",
                (self.store_key, key, payload),
            )

    def delete(self, key: str) -> None:
        with _conn() as c:
            c.execute(
                "DELETE FROM ui_state WHERE store_key=? AND key=?",
                (self.store_key, key),
            )

    def all(self) -> dict[str, Any]:
        with _conn() as c:
            rows = c.execute(
                "SELECT key, value FROM ui_state WHERE store_key=?", (self.store_key,)
            ).fetchall()
        out: dict[str, Any] = {}
        for k, v in rows:
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                continue
        return out

    def clear(self) -> None:
        with _conn() as c:
            c.execute("DELETE FROM ui_state WHERE store_key=?", (self.store_key,))
