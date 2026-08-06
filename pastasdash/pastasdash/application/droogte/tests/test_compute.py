"""Unit tests voor droogte/compute.py — geen I/O, geen netwerk."""

import numpy as np
import pandas as pd
import pytest

from pastasdash.application.droogte.compute import (
    comparison_year_series,
    cumulative_deficit_by_doy,
    current_year_series,
    daily_deficit,
    percentile_bands,
    pivot_by_doy,
    select_reference_years,
)


def _make_series(start: str, end: str, value: float, name: str = "s") -> pd.Series:
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(value, index=idx, name=name)


class TestDailyDeficit:
    def test_constant_inputs_gives_difference(self):
        prec = _make_series("2020-01-01", "2020-12-31", 2.0)
        evap = _make_series("2020-01-01", "2020-12-31", 3.0)
        result = daily_deficit(prec, evap)
        assert (result == 1.0).all()

    def test_more_rain_than_evap_gives_negative(self):
        prec = _make_series("2020-06-01", "2020-06-30", 5.0)
        evap = _make_series("2020-06-01", "2020-06-30", 2.0)
        result = daily_deficit(prec, evap)
        assert (result == -3.0).all()

    def test_mismatched_indices_filled_with_zero(self):
        prec = _make_series("2020-01-01", "2020-01-03", 1.0)
        evap = _make_series("2020-01-02", "2020-01-04", 1.0)
        result = daily_deficit(prec, evap)
        # 01-01: evap=0, prec=1 → -1
        # 01-02: evap=1, prec=1 →  0
        # 01-03: evap=1, prec=1 →  0
        # 01-04: evap=1, prec=0 → +1
        assert result.loc["2020-01-01"] == pytest.approx(-1.0)
        assert result.loc["2020-01-04"] == pytest.approx(1.0)


class TestCumulativeDeficit:
    def test_resets_each_year(self):
        prec = _make_series("2019-01-01", "2020-12-31", 1.0)
        evap = _make_series("2019-01-01", "2020-12-31", 2.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        # 1 jan elk jaar moet beginnen bij de waarde van die dag (not carry-over)
        assert cum.loc["2019-01-01"] == pytest.approx(1.0)
        assert cum.loc["2020-01-01"] == pytest.approx(1.0)

    def test_clip_negative_never_goes_below_zero(self):
        prec = _make_series("2020-01-01", "2020-12-31", 5.0)  # much rain
        evap = _make_series("2020-01-01", "2020-12-31", 1.0)
        deficit = daily_deficit(prec, evap)  # negative deficit (surplus)
        cum = cumulative_deficit_by_doy(deficit, clip_negative=True)
        assert (cum >= 0).all()

    def test_without_clip_can_go_negative(self):
        prec = _make_series("2020-01-01", "2020-12-31", 5.0)
        evap = _make_series("2020-01-01", "2020-12-31", 1.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit, clip_negative=False)
        assert cum.min() < 0


class TestPivotByDoy:
    def test_shape_and_columns(self):
        prec = _make_series("2019-01-01", "2021-12-31", 1.0)
        evap = _make_series("2019-01-01", "2021-12-31", 2.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        pivot = pivot_by_doy(cum)
        assert set(pivot.columns) == {2019, 2020, 2021}
        assert pivot.index.name == "doy"
        assert pivot.index.min() == 1


class TestPercentileBands:
    def test_returns_expected_columns(self):
        prec = _make_series("2000-01-01", "2020-12-31", 2.0)
        evap = _make_series("2000-01-01", "2020-12-31", 3.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        pivot = pivot_by_doy(cum)
        bands = percentile_bands(pivot)
        assert list(bands.columns) == ["p5", "p25", "p50", "p75", "p95"]

    def test_p50_equals_median(self):
        prec = _make_series("2000-01-01", "2020-12-31", 2.0)
        evap = _make_series("2000-01-01", "2020-12-31", 3.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        pivot = pivot_by_doy(cum)
        bands = percentile_bands(pivot)
        expected_median = pivot.median(axis=1)
        pd.testing.assert_series_equal(bands["p50"], expected_median, check_names=False)


class TestCurrentYear:
    def test_extracts_correct_year(self):
        prec = _make_series("2020-01-01", "2021-12-31", 1.5)
        evap = _make_series("2020-01-01", "2021-12-31", 2.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        s = current_year_series(cum, year=2020)
        assert s.name == "2020"
        assert s.index.min() == 1
        assert s.index.max() <= 366

    def test_defaults_to_last_year(self):
        prec = _make_series("2020-01-01", "2021-06-30", 1.5)
        evap = _make_series("2020-01-01", "2021-06-30", 2.0)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        s = current_year_series(cum)
        assert s.name == "2021"


class TestComparisonYears:
    def test_returns_df_with_year_columns(self):
        prec = _make_series("2018-01-01", "2021-12-31", 1.5)
        evap = _make_series("2018-01-01", "2021-12-31", 2.5)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        df = comparison_year_series(cum, [2018, 2020])
        assert set(df.columns) == {2018, 2020}

    def test_missing_year_skipped(self):
        prec = _make_series("2020-01-01", "2020-12-31", 1.5)
        evap = _make_series("2020-01-01", "2020-12-31", 2.5)
        deficit = daily_deficit(prec, evap)
        cum = cumulative_deficit_by_doy(deficit)
        df = comparison_year_series(cum, [2020, 2099])
        assert 2020 in df.columns
        assert 2099 not in df.columns


class TestSelectReferenceYears:
    def test_filters_correct_range(self):
        cols = list(range(1980, 2025))
        pivot = pd.DataFrame(0.0, index=range(1, 366), columns=cols)
        ref = select_reference_years(pivot, 1990, 2020)
        assert ref.columns.min() == 1990
        assert ref.columns.max() == 2020
