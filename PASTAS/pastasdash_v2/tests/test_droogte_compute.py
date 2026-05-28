"""Smoke-tests voor droogte compute-functies."""

from __future__ import annotations

import numpy as np
import pandas as pd

from pastasdash_v2.compute import droogte as d


def _synthetic_pe(n_years: int = 5) -> tuple[pd.Series, pd.Series]:
    idx = pd.date_range("2018-01-01", periods=365 * n_years, freq="D")
    rng = np.random.default_rng(seed=42)
    prec = pd.Series(rng.gamma(0.4, 4.0, len(idx)), index=idx, name="RH")
    evap = pd.Series(2.5 + np.sin(np.arange(len(idx)) * 2 * np.pi / 365) * 2.0, index=idx, name="EV24").clip(lower=0)
    return prec, evap


def test_daily_deficit_sign_convention():
    prec, evap = _synthetic_pe()
    deficit = d.daily_deficit(prec, evap)
    # Op dagen met EV24 > RH moet deficit positief zijn
    sample = (evap - prec)
    assert (deficit.dropna() == sample.dropna()).all()


def test_cumulative_resets_per_year():
    prec, evap = _synthetic_pe(n_years=3)
    cum = d.cumulative_deficit_by_doy(d.daily_deficit(prec, evap))
    # eerste dag van elk jaar = waarde van die ene dag (cumsum start opnieuw)
    for year in cum.index.year.unique():
        first = cum[cum.index == pd.Timestamp(f"{year}-01-01")]
        assert len(first) == 1


def test_pivot_and_bands_shapes():
    prec, evap = _synthetic_pe(n_years=5)
    cum = d.cumulative_deficit_by_doy(d.daily_deficit(prec, evap))
    pivot = d.pivot_by_doy(cum)
    assert pivot.index.name == "doy"
    bands = d.percentile_bands(pivot)
    for col in ("p5", "p25", "p50", "p75", "p95"):
        assert col in bands.columns


def test_current_year_indexed_by_doy():
    prec, evap = _synthetic_pe()
    cum = d.cumulative_deficit_by_doy(d.daily_deficit(prec, evap))
    s = d.current_year_series(cum)
    assert s.index.name == "doy"
    assert s.index.min() >= 1
    assert s.index.max() <= 366
