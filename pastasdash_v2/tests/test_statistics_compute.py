"""Tests voor pure functies in compute/statistics.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pastasdash_v2.core.statistics import (
    average_foe, classify_gt, frequency_of_exceedance, regime_curve,
)


@pytest.mark.unit
class TestClassifyGT:
    """Grondwatertrap-classificatie volgens STIBOKA."""

    def test_class_i_zeer_nat(self):
        assert classify_gt(ghg_cmmv=10, glg_cmmv=40) == "I"

    def test_class_ii_nat(self):
        assert classify_gt(ghg_cmmv=15, glg_cmmv=70) == "II"

    def test_class_iii(self):
        assert classify_gt(ghg_cmmv=20, glg_cmmv=100) == "III"

    def test_class_iii_ster(self):
        assert classify_gt(ghg_cmmv=30, glg_cmmv=100) == "III*"

    def test_class_iv(self):
        assert classify_gt(ghg_cmmv=60, glg_cmmv=100) == "IV"

    def test_class_v(self):
        assert classify_gt(ghg_cmmv=20, glg_cmmv=150) == "V"

    def test_class_vi(self):
        assert classify_gt(ghg_cmmv=60, glg_cmmv=150) == "VI"

    def test_class_vii(self):
        assert classify_gt(ghg_cmmv=100, glg_cmmv=200) == "VII"

    def test_class_viii_diep(self):
        assert classify_gt(ghg_cmmv=200, glg_cmmv=300) == "VIII"

    def test_invalid_input_returns_question_mark(self):
        assert classify_gt(ghg_cmmv=float("nan"), glg_cmmv=100) == "?"
        assert classify_gt(ghg_cmmv=20, glg_cmmv=float("nan")) == "?"


@pytest.mark.unit
class TestFrequencyOfExceedance:
    def test_empty_series_returns_empty_frame(self):
        result = frequency_of_exceedance(pd.Series(dtype=float))
        assert result.empty
        assert list(result.columns) == ["foe", "value"]

    def test_monotone_decreasing(self):
        idx = pd.date_range("2020-01-01", periods=10, freq="D")
        s = pd.Series(np.random.RandomState(42).rand(10), index=idx)
        result = frequency_of_exceedance(s)
        assert len(result) == 10
        # values moeten monotoon dalend zijn
        assert all(result["value"].values[:-1] >= result["value"].values[1:])
        # foe strikt stijgend in (0, 100)
        assert result["foe"].is_monotonic_increasing
        assert (result["foe"] > 0).all()
        assert (result["foe"] < 100).all()

    def test_average_foe_matches_single_series(self):
        idx = pd.date_range("2020-01-01", periods=50, freq="D")
        s = pd.Series(np.linspace(0, 1, 50), index=idx)
        avg = average_foe({"a": s})
        single = frequency_of_exceedance(s)
        # gemiddelde van 1 reeks moet ongeveer overeenkomen met de originele
        # (interpolatie op 1–99 grid)
        assert not avg.empty
        assert avg["value"].min() >= single["value"].min()
        assert avg["value"].max() <= single["value"].max()


@pytest.mark.unit
class TestRegimeCurve:
    def test_empty_series(self):
        assert regime_curve(pd.Series(dtype=float)).empty

    def test_month_aggregation(self):
        idx = pd.date_range("2020-01-01", "2020-12-31", freq="D")
        s = pd.Series(idx.month.astype(float), index=idx)
        rc = regime_curve(s, freq="month")
        assert len(rc) == 12
        # gemiddelde per maand moet gelijk zijn aan het maandnummer
        np.testing.assert_allclose(rc.values, np.arange(1, 13))

    def test_doy_aggregation(self):
        idx = pd.date_range("2020-01-01", "2020-12-31", freq="D")
        s = pd.Series(1.0, index=idx)
        rc = regime_curve(s, freq="doy")
        assert len(rc) == 366  # 2020 is een schrikkeljaar
        assert (rc == 1.0).all()
