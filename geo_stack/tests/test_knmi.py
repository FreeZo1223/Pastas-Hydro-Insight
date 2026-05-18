"""Unit-tests voor geo_stack.skills.knmi — alleen netwerk-loze paden.

De live KNMI-API (`daggegevens.knmi.nl`) is regelmatig instabiel (HTTP 500).
Integration-tests die de echte API aanroepen staan onder `@pytest.mark.integration`
en draaien niet in de standaard CI-run.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from geo_stack.skills.knmi import (
    fetch_knmi_dagwaarden,
    fetch_recharge_inputs,
    list_climate_stations,
    nearest_climate_station,
    to_neerslag_mm,
    to_verdamping_mm,
)


# ── Station-tabel ────────────────────────────────────────────────────────────

class TestClimateStations:
    def test_list_returns_known_stations(self):
        table = list_climate_stations()
        assert "260" in table  # De Bilt
        assert "310" in table  # Vlissingen
        lat, lon, name = table["260"]
        assert name == "De Bilt"
        assert 51.5 < lat < 52.5
        assert 4.5 < lon < 5.5

    def test_nearest_burgh_haamstede(self):
        # Burgh-Haamstede ligt in Zeeland
        stn, dist, name = nearest_climate_station(51.700, 3.737)
        assert stn in {"310", "323"}  # Vlissingen of Wilhelminadorp
        assert dist < 50

    def test_nearest_de_bilt_picks_itself(self):
        stn, dist, name = nearest_climate_station(52.100, 5.180)
        assert stn == "260"
        assert dist < 1.0


# ── Conversies (mm-omrekening, missing flag) ─────────────────────────────────

class TestConversions:
    def test_neerslag_converts_tenths_to_mm(self):
        df = pd.DataFrame({"RD": [10, 25, -1, 0]})
        s = to_neerslag_mm(df)
        assert s.iloc[0] == pytest.approx(1.0)
        assert s.iloc[1] == pytest.approx(2.5)
        assert pd.isna(s.iloc[2])
        assert s.iloc[3] == pytest.approx(0.0)
        assert s.name == "Neerslag_mm"

    def test_verdamping_converts_tenths_to_mm(self):
        df = pd.DataFrame({"EV24": [5, 30, -1]})
        s = to_verdamping_mm(df)
        assert s.iloc[0] == pytest.approx(0.5)
        assert s.iloc[1] == pytest.approx(3.0)
        assert pd.isna(s.iloc[2])

    def test_neerslag_missing_column_raises(self):
        with pytest.raises(ValueError, match="RD"):
            to_neerslag_mm(pd.DataFrame({"EV24": [1, 2]}))

    def test_verdamping_missing_column_raises(self):
        with pytest.raises(ValueError, match="EV24"):
            to_verdamping_mm(pd.DataFrame({"RD": [1, 2]}))


# ── Integration (live KNMI — instabiel, alleen op verzoek) ───────────────────

@pytest.mark.integration
class TestKnmiLive:
    def test_fetch_recharge_de_bilt(self):
        prec, evap = fetch_recharge_inputs("260", start="2024-01-01", end="2024-01-07")
        assert len(prec) == 7
        assert len(evap) == 7
        assert prec.notna().any()
        assert evap.notna().any()
