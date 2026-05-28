"""Droogte-compute: cumulatief neerslagtekort, percentielbanden, jaarvergelijking.

Pure functies — geport vanuit pastasdash v1 droogte/compute.py.
"""

from __future__ import annotations

import pandas as pd


def daily_deficit(prec: pd.Series, evap: pd.Series) -> pd.Series:
    """Bereken dagelijks neerslagtekort in mm (evap - prec)."""
    idx = prec.index.union(evap.index)
    p = prec.reindex(idx, fill_value=0.0)
    e = evap.reindex(idx, fill_value=0.0)
    deficit = e - p
    deficit.name = "deficit_mm"
    return deficit


def cumulative_deficit_by_doy(deficit: pd.Series, clip_negative: bool = False) -> pd.Series:
    """Cumulatief tekort, gereset op 1 januari per jaar."""
    deficit = deficit.sort_index()
    result = deficit.copy()
    for _, grp in deficit.groupby(deficit.index.year):
        cum = grp.cumsum()
        if clip_negative:
            cum = cum.clip(lower=0.0)
        result.loc[grp.index] = cum.values
    result.name = "cum_deficit_mm"
    return result


def pivot_by_doy(cum_deficit: pd.Series) -> pd.DataFrame:
    """doy × jaar matrix."""
    df = pd.DataFrame(
        {
            "doy": cum_deficit.index.dayofyear,
            "year": cum_deficit.index.year,
            "value": cum_deficit.values,
        }
    )
    pivot = df.pivot_table(index="doy", columns="year", values="value", aggfunc="mean")
    pivot.index.name = "doy"
    return pivot


def percentile_bands(
    cum_by_year: pd.DataFrame,
    percentiles: tuple[float, ...] = (5, 25, 50, 75, 95),
) -> pd.DataFrame:
    """Percentielbanden per doy."""
    result = cum_by_year.quantile([p / 100.0 for p in percentiles], axis=1).T
    result.columns = [f"p{int(p)}" for p in percentiles]
    result.index.name = "doy"
    return result


def select_reference_years(pivot: pd.DataFrame, ref_start: int, ref_end: int) -> pd.DataFrame:
    years = [y for y in pivot.columns if ref_start <= y <= ref_end]
    return pivot[years]


def current_year_series(cum_deficit: pd.Series, year: int | None = None) -> pd.Series:
    if year is None:
        year = int(cum_deficit.index.year.max())
    s = cum_deficit[cum_deficit.index.year == year].copy()
    s.index = s.index.dayofyear
    s.index.name = "doy"
    s.name = str(year)
    return s


def comparison_year_series(cum_deficit: pd.Series, years: list[int]) -> pd.DataFrame:
    frames: dict[int, pd.Series] = {}
    for yr in years:
        s = cum_deficit[cum_deficit.index.year == yr]
        if s.empty:
            continue
        s = s.copy()
        s.index = s.index.dayofyear
        frames[yr] = s
    return pd.DataFrame(frames) if frames else pd.DataFrame()
