"""Tijdreeks-helpers: stats, GxG, oseries-aggregaties (gecached)."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pastas as ps

from pastasdash_v2.core.cache import memoize
from pastasdash_v2.core.config import GXG_MIN_N_MEAS, GXG_MIN_N_YEARS
from pastasdash_v2.core.store import STORE

log = logging.getLogger(__name__)


def get_oseries(name: str) -> pd.Series:
    s = STORE.pstore.get_oseries(name)
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0] if s.shape[1] >= 1 else pd.Series(dtype=float)
    return s.dropna()


def get_stress(name: str) -> pd.Series:
    s = STORE.pstore.get_stresses(name)
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0] if s.shape[1] >= 1 else pd.Series(dtype=float)
    return s.dropna()


@memoize("ts_stats")
def timeseries_stats(store_key: str, name: str) -> dict:
    s = get_oseries(name)
    if s.empty:
        return {"tmin": None, "tmax": None, "n_observations": 0, "mean": np.nan, "std": np.nan}
    return {
        "tmin": s.index.min().isoformat(),
        "tmax": s.index.max().isoformat(),
        "n_observations": int(s.size),
        "mean": float(s.mean()),
        "std": float(s.std()),
    }


def _n_valid_hydroyears(s: pd.Series) -> int:
    """Aantal hydrologische jaren dat pastas daadwerkelijk bruikbaar vindt.

    Bewust via ``pastas`` zelf (``output="yearly"``) en niet met een eigen
    telling: pastas vult de 14e/28e aan met ``fill_method="nearest"``, dus
    handmatig tellen geeft een lager — en dus misleidend — getal dan waarop
    pastas zijn ``min_n_years``-toets baseert.

    Puur informatief: hiermee kan de UI uitleggen *waarom* een GxG leeg blijft.
    """
    if s.empty:
        return 0
    try:
        yearly = ps.stats.glg(
            s, min_n_meas=GXG_MIN_N_MEAS, min_n_years=0, output="yearly"
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("Kon geldige hydrojaren niet bepalen: %s", exc)
        return 0
    return int(pd.Series(yearly).notna().sum())


@memoize("gxg")
def gxg(store_key: str, name: str) -> dict:
    """GHG, GLG en GVG via de officiële ``pastas.stats``-implementaties.

    Bewust *niet* zelf uitgerekend: pastas hanteert de STIBOKA-conventie
    (14e/28e van de maand, hydrologisch jaar apr–mrt) en laat onvolledige
    jaren vallen. Zelf middelen over alle jaren vertekent de GLG met
    ruim een decimeter zodra de reeks met een half jaar begint of eindigt,
    en dat werkt door in de grondwatertrap.

    Resultaten in dezelfde eenheid als de oseries (meestal m NAP);
    ``NaN`` als de reeks te kort is voor een verantwoorde uitspraak.
    """
    s = get_oseries(name)
    n_years = _n_valid_hydroyears(s)
    if s.empty:
        return {"GHG": np.nan, "GLG": np.nan, "GVG": np.nan, "n_years": 0}

    def _safe(fn, min_n_meas: int = GXG_MIN_N_MEAS) -> float:
        try:
            return float(fn(s, min_n_meas=min_n_meas, min_n_years=GXG_MIN_N_YEARS))
        except Exception as exc:  # noqa: BLE001
            log.warning("%s faalde voor %s: %s", fn.__name__, name, exc)
            return np.nan

    return {
        "GHG": _safe(ps.stats.ghg),
        "GLG": _safe(ps.stats.glg),
        # GVG kent per jaar maar drie meetmomenten (14 mrt, 28 mrt, 14 apr)
        # en heeft in pastas daarom een eigen, lagere drempel.
        "GVG": _safe(ps.stats.gvg, min_n_meas=2),
        "n_years": n_years,
    }


@memoize("model_results")
def model_summary(store_key: str, model_name: str) -> dict:
    """Korte modelsamenvatting (R², EVP, parameters)."""
    try:
        ml = STORE.pstore.get_models(model_name)
        if ml is None:
            return {}
        stats = ml.stats.summary()
        return {
            "rsq": float(stats.loc["Rsq", "Value"]) if "Rsq" in stats.index else np.nan,
            "evp": float(stats.loc["EVP", "Value"]) if "EVP" in stats.index else np.nan,
            "n_obs": int(ml.oseries.series.size),
            "tmin": ml.settings["tmin"].isoformat() if ml.settings.get("tmin") else None,
            "tmax": ml.settings["tmax"].isoformat() if ml.settings.get("tmax") else None,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("model_summary faalde voor %s: %s", model_name, exc)
        return {}
