"""Schone, explicit-typed wrapper rond PastaStore.

Geen monkey-patching, geen ``setattr``-magic. Eén globaal singleton (``STORE``)
dat door alle pagina's geraadpleegd wordt. UI-laag observert state-changes
via ``on_change`` callbacks.
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import pastastore as pst
import pyproj

from pastasdash_v2.config import CRS_RD, CRS_WGS84, DEFAULT_COLUMNS, ColumnMapping
from pastasdash_v2.state.persistence import AppState, UIState

log = logging.getLogger(__name__)


def _looks_like_bro_loket_zip(path: Path) -> bool:
    if not path.exists() or path.is_dir() or path.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            return any("BRO_Grondwatermonitoringput" in n and n.endswith(".xml") for n in zf.namelist())
    except Exception:  # noqa: BLE001
        return False


def _looks_like_bro_loket_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(path.rglob("GMW*.xml"))
    except Exception:  # noqa: BLE001
        return False


def _store_key(path: Path) -> str:
    """Canonieke key voor cache + UI-state per store."""
    return str(path.resolve()).replace("\\", "/")


def _build_pastastore_from_bro(path: Path) -> pst.PastaStore:
    """Lazy import: lesa_agent.bro_loket_cli alleen laden als nodig."""
    try:
        from lesa_agent.bro_loket_cli import bro_loket_zip_to_pastastore
    except ImportError as exc:
        raise RuntimeError(
            "lesa_agent niet geïnstalleerd. Installeer met:\n"
            "  pip install -e ../../lesa-agent-v2/packages/lesa_agent"
        ) from exc
    return bro_loket_zip_to_pastastore(path, verbose=False)


class StoreManager:
    """Houdt de actieve PastaStore vast en publiceert wijzigingen."""

    def __init__(self, columns: ColumnMapping = DEFAULT_COLUMNS) -> None:
        self._pstore: pst.PastaStore | None = None
        self._source_path: Path | None = None
        self._store_key: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self.columns = columns

    # ── publieke properties ────────────────────────────────────────────────
    @property
    def is_loaded(self) -> bool:
        return self._pstore is not None

    @property
    def pstore(self) -> pst.PastaStore:
        if self._pstore is None:
            raise RuntimeError("Geen PastaStore geladen.")
        return self._pstore

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    @property
    def store_key(self) -> str:
        if self._store_key is None:
            raise RuntimeError("Geen PastaStore geladen.")
        return self._store_key

    @property
    def display_name(self) -> str:
        if self._source_path is None:
            return "(geen store geladen)"
        return self._source_path.name

    @property
    def ui_state(self) -> UIState:
        return UIState(self.store_key)

    # ── loading ────────────────────────────────────────────────────────────
    def load_from_path(self, path: str | Path) -> None:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Pad bestaat niet: {p}")

        if p.is_dir():
            if not _looks_like_bro_loket_dir(p):
                raise ValueError(f"Map bevat geen BRO Loket-export: {p}")
            log.info("BRO Loket-map gedetecteerd: %s", p)
            store = _build_pastastore_from_bro(p)
        elif _looks_like_bro_loket_zip(p):
            log.info("BRO Loket-ZIP gedetecteerd: %s", p)
            store = _build_pastastore_from_bro(p)
        else:
            log.info("Native PastaStore-ZIP laden: %s", p)
            store = pst.PastaStore.from_zip(p)

        self._set_store(store, p)

    def load_from_zip_bytes(self, blob: bytes, original_name: str) -> None:
        """Voor upload via NiceGUI ui.upload."""
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(suffix=Path(original_name).suffix or ".zip", delete=False) as tmp:
            tmp.write(blob)
            tmp_path = Path(tmp.name)
        try:
            self.load_from_path(tmp_path)
            # store_key blijft de tmp-path; vervang door upload-naam zodat cache stabieler is
            stable_key = f"upload:{hashlib.sha1(blob).hexdigest()[:16]}:{original_name}"
            self._store_key = stable_key
            AppState.set("last_store_path", original_name)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def close(self) -> None:
        self._pstore = None
        self._source_path = None
        self._store_key = None
        AppState.delete("last_store_path")
        self._notify()

    def _set_store(self, store: pst.PastaStore, path: Path) -> None:
        self._pstore = store
        self._source_path = path
        self._store_key = _store_key(path)
        AppState.set("last_store_path", str(path))
        self._notify()

    # ── reactive listeners ─────────────────────────────────────────────────
    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb()
            except Exception as exc:  # noqa: BLE001
                log.warning("Listener faalde: %s", exc)

    # ── geprojecteerde dataframes ──────────────────────────────────────────
    def oseries(self) -> pd.DataFrame:
        """oseries-tabel verrijkt met lat/lon en z-coordinaat."""
        if not self.is_loaded:
            return _empty_oseries(self.columns)
        df = self._pstore.oseries.copy()
        if df.empty:
            return _empty_oseries(self.columns)
        df = _add_latlon(df, self.columns)
        df["kind"] = "oseries"
        cols = self.columns
        if cols.screen_top in df.columns and cols.screen_bottom in df.columns:
            df["z"] = df[[cols.screen_top, cols.screen_bottom]].mean(axis=1)
        else:
            df["z"] = np.nan
        df["n_observations"] = [
            self._pstore.oseries.loc[name].get("n_observations", np.nan) for name in df.index
        ]
        df["id"] = np.arange(len(df))
        return df.sort_values("z", na_position="last")

    def stresses(self) -> pd.DataFrame:
        if not self.is_loaded:
            return _empty_stresses()
        df = self._pstore.stresses.copy()
        if df.empty:
            return _empty_stresses()
        df = _add_latlon(df, self.columns)
        df["id"] = np.arange(len(df))
        return df

    def model_names(self) -> list[str]:
        if not self.is_loaded:
            return []
        try:
            return list(self._pstore.model_names)
        except Exception:  # noqa: BLE001
            return []

    def oseries_names(self) -> list[str]:
        if not self.is_loaded:
            return []
        return list(self._pstore.oseries_names)


# ── helpers ────────────────────────────────────────────────────────────────
def _add_latlon(df: pd.DataFrame, cols: ColumnMapping) -> pd.DataFrame:
    if cols.x not in df.columns or cols.y not in df.columns:
        df["lat"] = np.nan
        df["lon"] = np.nan
        return df
    if "lat" in df.columns and "lon" in df.columns:
        return df
    tf = pyproj.Transformer.from_crs(CRS_RD, CRS_WGS84, always_xy=True)
    lon, lat = tf.transform(df[cols.x].values, df[cols.y].values)
    df["lat"] = lat
    df["lon"] = lon
    return df


def _empty_oseries(cols: ColumnMapping) -> pd.DataFrame:
    return pd.DataFrame(
        columns=["kind", cols.x, cols.y, "z", "lat", "lon", cols.screen_top, cols.screen_bottom, "id", "n_observations"]
    )


def _empty_stresses() -> pd.DataFrame:
    return pd.DataFrame(columns=["kind", "x", "y", "lat", "lon", "id"])


# ── module-singleton ───────────────────────────────────────────────────────
STORE = StoreManager()


def restore_last_store() -> None:
    """Laad bij opstart automatisch de laatst-gebruikte store als die nog bestaat."""
    last = AppState.get("last_store_path")
    if not last:
        return
    p = Path(last)
    if not p.exists():
        log.info("Laatst gebruikte store-pad bestaat niet meer: %s", p)
        AppState.delete("last_store_path")
        return
    try:
        STORE.load_from_path(p)
        log.info("Herstart-restore: %s geladen.", p.name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Restore van %s faalde: %s", p, exc)
