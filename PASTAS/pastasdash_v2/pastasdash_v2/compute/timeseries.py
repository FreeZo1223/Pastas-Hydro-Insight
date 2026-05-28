"""Tijdreeks-helpers: stats, GxG, oseries-aggregaties (gecached)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from pastasdash_v2.state.cache import memoize
from pastasdash_v2.state.store import STORE

if TYPE_CHECKING:
    import pastas as ps

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


@memoize("gxg")
def gxg(store_key: str, name: str) -> dict:
    """GHG, GLG, GVG volgens veelgebruikte definitie (3-jaar gemiddelde van uitersten).

    Resultaten in dezelfde eenheid als de oseries (meestal m NAP).
    """
    s = get_oseries(name)
    if s.empty or s.size < 3 * 24:  # minimaal ~3 jaar tweewekelijks
        return {"GHG": np.nan, "GLG": np.nan, "GVG": np.nan}

    # 14e en 28e van elke maand (Nederlandse hydrologische conventie)
    biweekly = s[s.index.day.isin([14, 28])]
    if biweekly.empty:
        biweekly = s.resample("SMS").mean()

    by_hydroyear = biweekly.groupby((biweekly.index - pd.DateOffset(months=3)).year)
    hg3 = by_hydroyear.apply(lambda g: g.nlargest(3).mean())
    lg3 = by_hydroyear.apply(lambda g: g.nsmallest(3).mean())
    ghg = float(hg3.mean()) if not hg3.empty else np.nan
    glg = float(lg3.mean()) if not lg3.empty else np.nan

    # GVG: gemiddelde van 14-mrt, 28-mrt, 14-apr per jaar
    spring = s[
        ((s.index.month == 3) & (s.index.day.isin([14, 28])))
        | ((s.index.month == 4) & (s.index.day == 14))
    ]
    gvg = float(spring.groupby(spring.index.year).mean().mean()) if not spring.empty else np.nan

    return {"GHG": ghg, "GLG": glg, "GVG": gvg}


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
