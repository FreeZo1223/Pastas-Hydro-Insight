"""Tests voor droogte/data.py — netwerk gemockt."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pastasdash.application.droogte.data import (
    _cache_path,
    _is_fresh,
    fetch_knmi_daily,
)


def _make_df(start: str = "2020-01-01", end: str = "2020-12-31") -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="D", name="datum")
    return pd.DataFrame({"RH": 2.0, "EV24": 3.0}, index=idx)


class TestCachePath:
    def test_includes_station_and_year(self):
        p = _cache_path(260, 1990)
        assert "260" in p.name
        assert "1990" in p.name
        assert p.suffix == ".parquet"


class TestIsFresh:
    def test_nonexistent_file_is_not_fresh(self, tmp_path):
        p = tmp_path / "nonexistent.parquet"
        assert _is_fresh(p) is False

    def test_fresh_file_is_fresh(self, tmp_path):
        p = tmp_path / "fresh.parquet"
        p.write_bytes(b"dummy")
        # Modify mtime to now
        import time; p.touch()
        assert _is_fresh(p) is True

    def test_old_file_is_not_fresh(self, tmp_path):
        p = tmp_path / "old.parquet"
        p.write_bytes(b"dummy")
        import os, time
        old_time = time.time() - 3 * 86400  # 3 days old
        os.utime(p, (old_time, old_time))
        assert _is_fresh(p) is False


class TestFetchKnmiDaily:
    def test_returns_rh_and_ev24_columns(self, tmp_path):
        mock_df = _make_df()
        with (
            patch("pastasdash.application.droogte.data._cache_path", return_value=tmp_path / "c.parquet"),
            patch("pastasdash.application.droogte.data._is_fresh", return_value=False),
            patch("pastasdash.application.droogte.data._fetch_via_hydropandas", return_value=mock_df),
        ):
            df = fetch_knmi_daily(260, start_year=2020, end_year=2020)
        assert "RH" in df.columns
        assert "EV24" in df.columns

    def test_uses_cache_when_fresh(self, tmp_path):
        mock_df = _make_df()
        cache_file = tmp_path / "260_1990.parquet"
        mock_df.to_parquet(cache_file)

        with (
            patch("pastasdash.application.droogte.data._cache_path", return_value=cache_file),
            patch("pastasdash.application.droogte.data._is_fresh", return_value=True),
        ):
            df = fetch_knmi_daily(260)
        assert not df.empty

    def test_falls_back_to_url_when_hydropandas_fails(self, tmp_path):
        mock_df = _make_df()
        with (
            patch("pastasdash.application.droogte.data._cache_path", return_value=tmp_path / "c.parquet"),
            patch("pastasdash.application.droogte.data._is_fresh", return_value=False),
            patch("pastasdash.application.droogte.data._fetch_via_hydropandas", side_effect=RuntimeError("fail")),
            patch("pastasdash.application.droogte.data._fetch_via_knmi_url", return_value=mock_df),
        ):
            df = fetch_knmi_daily(260, start_year=2020, end_year=2020)
        assert not df.empty
