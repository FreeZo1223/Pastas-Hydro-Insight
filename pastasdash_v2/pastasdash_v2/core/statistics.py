"""Statistiek-helpers voor de Statistics-tab (Menyanthes-stijl).

Reproduceert de Menyanthes ``Groundwater Level Statistics`` functies:
- GxG (GHG/GLG/GVG) en gemiddelde grondwaterstand (MG)
- Grondwatertrap (GT, Romeins I–VIII) op basis van GHG/GLG in cm-mv
- Frequency of Exceedance curve (empirische CDF, gesorteerd aflopend)
- Regime curve (gemiddelde per maand/decade)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pastasdash_v2.core.cache import memoize
from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import get_oseries, gxg

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GwStats:
    """Statistieken voor één peilbuis, in m NAP."""

    name: str
    gt: str
    mlgl: float  # = GLG
    mg: float    # gemiddelde
    msgl: float  # = GVG
    mhgl: float  # = GHG
    surface_level: float


# ── Grondwatertrap (GT) ────────────────────────────────────────────────────
def classify_gt(ghg_cmmv: float, glg_cmmv: float) -> str:
    """Klassieke Nederlandse Grondwatertrap (zonder sub-klassen).

    Beide invoerwaarden in **cm beneden maaiveld** (positief omlaag).
    Retourneert Romeinse cijfers I–VIII of "?" als invoer ontbreekt.
    Bron: STIBOKA-classificatie zoals gebruikt in Menyanthes.
    """
    if not np.isfinite(ghg_cmmv) or not np.isfinite(glg_cmmv):
        return "?"

    # GLG bepaalt eerst de hoofdklasse
    if glg_cmmv < 50:
        return "I"
    if glg_cmmv < 80:
        return "II"
    if glg_cmmv < 120:
        if ghg_cmmv < 25:
            return "III"
        if ghg_cmmv < 40:
            return "III*"
        return "IV"
    # glg >= 120
    if ghg_cmmv < 25:
        return "V"
    if ghg_cmmv < 40:
        return "V*"
    if ghg_cmmv < 80:
        return "VI"
    if ghg_cmmv < 140:
        return "VII"
    return "VIII"


def _surface_level(name: str) -> float:
    """Maaiveldhoogte (m NAP) uit oseries-metadata; NaN indien afwezig."""
    try:
        row = STORE.pstore.oseries.loc[name]
    except (KeyError, AttributeError):
        return float("nan")
    col = STORE.columns.ground_level
    if col not in row.index:
        return float("nan")
    val = row[col]
    if pd.isna(val):
        return float("nan")
    return float(val)


@memoize("gw_stats")
def gw_stats(store_key: str, name: str) -> dict:
    """Volledige statistiek-dict voor één peilbuis (gecached)."""
    g = gxg(store_key, name)
    s = get_oseries(name)
    mg = float(s.mean()) if not s.empty else float("nan")
    sl = _surface_level(name)

    ghg = g.get("GHG", float("nan"))
    glg = g.get("GLG", float("nan"))
    gvg = g.get("GVG", float("nan"))

    if np.isfinite(sl) and np.isfinite(ghg) and np.isfinite(glg):
        ghg_cmmv = (sl - ghg) * 100.0
        glg_cmmv = (sl - glg) * 100.0
        gt = classify_gt(ghg_cmmv, glg_cmmv)
    else:
        gt = "?"

    return {
        "name": name,
        "gt": gt,
        "mlgl": glg,
        "mg": mg,
        "msgl": gvg,
        "mhgl": ghg,
        "surface_level": sl,
    }


# ── Frequency of Exceedance ────────────────────────────────────────────────
def frequency_of_exceedance(series: pd.Series) -> pd.DataFrame:
    """Empirische FOE-curve: sorteer aflopend, geef rang-percentage.

    Resultaat: DataFrame met kolommen ``foe`` (0–100 %) en ``value``.
    """
    s = series.dropna()
    if s.empty:
        return pd.DataFrame(columns=["foe", "value"])
    vals = np.sort(s.values)[::-1]
    n = vals.size
    # Plotting position (Weibull): i / (n+1) * 100, met i=1..n
    foe = np.arange(1, n + 1, dtype=float) / (n + 1) * 100.0
    return pd.DataFrame({"foe": foe, "value": vals})


def average_foe(series_dict: dict[str, pd.Series]) -> pd.DataFrame:
    """Gemiddelde FOE-curve over meerdere reeksen (op een gemeenschappelijke FOE-grid)."""
    if not series_dict:
        return pd.DataFrame(columns=["foe", "value"])
    grid = np.arange(1, 100, 1, dtype=float)
    interp_cols = []
    for s in series_dict.values():
        foe = frequency_of_exceedance(s)
        if foe.empty:
            continue
        interp = np.interp(grid, foe["foe"].values, foe["value"].values)
        interp_cols.append(interp)
    if not interp_cols:
        return pd.DataFrame(columns=["foe", "value"])
    avg = np.mean(np.vstack(interp_cols), axis=0)
    return pd.DataFrame({"foe": grid, "value": avg})


# ── Regime curve ───────────────────────────────────────────────────────────
def regime_curve(series: pd.Series, freq: str = "month") -> pd.Series:
    """Gemiddelde grondwaterstand per maand (1–12) of dag-van-jaar (1–366).

    ``freq``: "month" of "doy".
    Retourneert pd.Series met index = maand/doy en waarde = gemiddelde.
    """
    s = series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    if freq == "doy":
        key = s.index.dayofyear
    else:
        key = s.index.month
    out = s.groupby(key).mean()
    out.name = series.name
    return out
