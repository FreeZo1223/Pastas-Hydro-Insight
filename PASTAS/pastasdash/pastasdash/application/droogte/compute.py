"""Bereken cumulatief neerslagtekort en statistieken per dag-van-het-jaar.

Alle functies zijn puur (geen I/O, geen netwerk) en goed testbaar.

Definitie neerslagtekort (Thornthwaite):
    tekort[t] = EV24[t] - RH[t]         (mm/d; positief = uitdroging)
    cumulatief tekort[t] = cumsum(tekort) reset per jaar op 1 jan

Een positieve cumulatieve waarde betekent dat de evapotranspiratie de
neerslag overtrof (droogte). Negatieve waarden = neerslagoverschot.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def daily_deficit(prec: pd.Series, evap: pd.Series) -> pd.Series:
    """Bereken dagelijks neerslagtekort in mm.

    Parameters
    ----------
    prec:
        Dagelijkse neerslag RH in mm (DatetimeIndex).
    evap:
        Dagelijkse Makkink-verdamping EV24 in mm (DatetimeIndex).

    Returns
    -------
    pd.Series
        Dagelijks tekort (evap - prec), mm.  Positief = droger.
    """
    idx = prec.index.union(evap.index)
    p = prec.reindex(idx, fill_value=0.0)
    e = evap.reindex(idx, fill_value=0.0)
    deficit = e - p
    deficit.name = "deficit_mm"
    return deficit


def cumulative_deficit_by_doy(deficit: pd.Series, clip_negative: bool = False) -> pd.Series:
    """Bereken cumulatief neerslagtekort, gereset op 1 januari elk jaar.

    Parameters
    ----------
    deficit:
        Dagelijks tekort (mm), DatetimeIndex.
    clip_negative:
        Als True worden negatieve cumulatieve waarden op 0 gehouden
        (tekort kan nooit 'ingehaald' worden). Default False.

    Returns
    -------
    pd.Series
        Cumulatief tekort met dezelfde index als ``deficit``.
    """
    deficit = deficit.sort_index()
    result = deficit.copy()
    for year, grp in deficit.groupby(deficit.index.year):
        cum = grp.cumsum()
        if clip_negative:
            cum = cum.clip(lower=0.0)
        result.loc[grp.index] = cum.values
    result.name = "cum_deficit_mm"
    return result


def percentile_bands(
    cum_by_year: pd.DataFrame,
    percentiles: tuple[float, ...] = (5, 25, 50, 75, 95),
) -> pd.DataFrame:
    """Bereken percentielbanden per dag-van-het-jaar.

    Parameters
    ----------
    cum_by_year:
        DataFrame met kolom per jaar en index = dag-van-het-jaar (1…366).
        Maak dit met :func:`pivot_by_doy`.
    percentiles:
        Welke percentielen te berekenen.

    Returns
    -------
    pd.DataFrame
        Index = doy (1…366), kolommen = percentielen (bijv. 'p5', 'p50', …).
    """
    result = cum_by_year.quantile([p / 100.0 for p in percentiles], axis=1).T
    result.columns = [f"p{int(p)}" for p in percentiles]
    result.index.name = "doy"
    return result


def pivot_by_doy(cum_deficit: pd.Series) -> pd.DataFrame:
    """Zet een tijdreeks van cumulatief tekort om naar een doy × jaar matrix.

    Parameters
    ----------
    cum_deficit:
        Cumulatief dagelijks tekort (DatetimeIndex).

    Returns
    -------
    pd.DataFrame
        Index = doy (1…366), kolommen = jaren.  Ontbrekende doy's krijgen NaN.
    """
    df = pd.DataFrame(
        {"doy": cum_deficit.index.dayofyear, "year": cum_deficit.index.year, "value": cum_deficit.values}
    )
    pivot = df.pivot_table(index="doy", columns="year", values="value", aggfunc="mean")
    pivot.index.name = "doy"
    return pivot


def select_reference_years(pivot: pd.DataFrame, ref_start: int, ref_end: int) -> pd.DataFrame:
    """Filter kolommen op referentieperiode [ref_start, ref_end] (inclusief)."""
    years = [y for y in pivot.columns if ref_start <= y <= ref_end]
    return pivot[years]


def current_year_series(cum_deficit: pd.Series, year: int | None = None) -> pd.Series:
    """Extraheer het huidige jaar als doy-geïndexeerde reeks.

    Parameters
    ----------
    cum_deficit:
        Tijdreeks cumulatief tekort.
    year:
        Jaar om te extraheren; None = laatste jaar in de reeks.

    Returns
    -------
    pd.Series
        Index = doy, name = str(year).
    """
    if year is None:
        year = cum_deficit.index.year.max()
    s = cum_deficit[cum_deficit.index.year == year]
    s = s.copy()
    s.index = s.index.dayofyear
    s.index.name = "doy"
    s.name = str(year)
    return s


def comparison_year_series(cum_deficit: pd.Series, years: list[int]) -> pd.DataFrame:
    """Extraheer meerdere vergelijkingsjaren als doy × jaar DataFrame."""
    frames: dict[int, pd.Series] = {}
    for yr in years:
        s = cum_deficit[cum_deficit.index.year == yr]
        if s.empty:
            continue
        s = s.copy()
        s.index = s.index.dayofyear
        frames[yr] = s
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames)
