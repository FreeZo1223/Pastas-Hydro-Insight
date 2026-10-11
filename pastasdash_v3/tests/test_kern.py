"""Tests voor de rekenlaag van v3, zonder netwerk en zonder browser.

Draaien met de omgeving van v2 (daar staan pastas en pastastore):

    cd pastasdash_v2
    uv run --extra dev python -m pytest ../pastasdash_v3/tests -q
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from pastasdash_v2.core.stations import STATIONS_BY_CODE
from pastasdash_v2.core.store import STORE
from pastasdash_v3 import bro, brug, meteo, project

PUT_XML = """<?xml version="1.0"?>
<dispatchDataResponse xmlns="http://www.broservices.nl/xsd/dsgmw/1.1"
    xmlns:brocom="http://www.broservices.nl/xsd/brocommon/3.0"
    xmlns:gmwcommon="http://www.broservices.nl/xsd/gmwcommon/1.1"
    xmlns:gml="http://www.opengis.net/gml/3.2">
  <dispatchDocument><GMW_PO>
    <brocom:broId>GMW000000069526</brocom:broId>
    <nitgCode>B42C0133</nitgCode><wellCode>GMW42C000133</wellCode>
    <deliveredLocation><gmwcommon:location><gml:pos>26775.000 400400.000</gml:pos></gmwcommon:location></deliveredLocation>
    <deliveredVerticalPosition><gmwcommon:groundLevelPosition uom="m">3.430</gmwcommon:groundLevelPosition></deliveredVerticalPosition>
    <standardizedLocation><brocom:location><gml:pos>51.577 3.537</gml:pos></brocom:location></standardizedLocation>
    <monitoringTube><tubeNumber>2</tubeNumber><tubeTopPosition uom="m">3.980</tubeTopPosition>
      <screen><screenTopPosition uom="m">-2.870</screenTopPosition><screenBottomPosition uom="m">-3.870</screenBottomPosition></screen></monitoringTube>
    <monitoringTube><tubeNumber>1</tubeNumber><tubeTopPosition uom="m">4.030</tubeTopPosition>
      <screen><screenTopPosition uom="m">1.950</screenTopPosition><screenBottomPosition uom="m">0.950</screenBottomPosition></screen></monitoringTube>
  </GMW_PO></dispatchDocument>
</dispatchDataResponse>"""

AFWIJZING_XML = """<?xml version="1.0"?>
<dispatchDataResponse xmlns="http://www.broservices.nl/xsd/dsgmw/1.1" xmlns:brocom="http://www.broservices.nl/xsd/brocommon/3.0">
  <brocom:responseType>rejection</brocom:responseType>
  <brocom:rejectionReason>Registratieobject GMW000000000000 bestaat niet.</brocom:rejectionReason>
</dispatchDataResponse>"""

# 789994800000 ms = 13 januari 1995 11:00 UTC = 12:00 in wintertijd; de tweede regel is een uur later.
REEKS_CSV = (
    "Tijdstip,Voorlopige Waarde [m],Voorlopige Opmerking,Beoordeelde Waarde [m],Beoordeelde Opmerking,"
    "Controle Waarde [m],Controle Opmerking,Onbekend Waarde [m],Onbekend Opmerking\n"
    "789994800000,,,,,,,1.100,\n"
    "789998400000,1.300,,1.200,,,,,\n"
    "791204400000,1.270,,,,,,,\n"
)


@pytest.fixture
def leeg_project(tmp_path, monkeypatch):
    monkeypatch.setattr(brug, "PROJECTEN", tmp_path / "project")
    monkeypatch.setattr(brug, "UITVOER", tmp_path / "uit")
    uit = json.loads(brug.roep("nieuw_project", json.dumps({"naam": "proef project"})))
    assert uit["ok"]["naam"] == "proef_project"
    yield tmp_path
    STORE._pstore = None
    STORE._source_path = None
    STORE._store_key = None


def _dagreeksen(jaren: int = 6):
    rng = np.random.default_rng(1)
    idx = pd.date_range("2010-01-01", periods=jaren * 365, freq="D")
    prec = pd.Series(rng.gamma(0.4, 5.0, idx.size), index=idx)
    evap = pd.Series(1.5 * (1 - np.cos(2 * np.pi * idx.dayofyear / 365.25)), index=idx)
    stand = 1.0 + 0.004 * np.convolve((prec - evap).to_numpy(), np.exp(-np.arange(200) / 40.0))[: idx.size]
    stand = pd.Series(stand + rng.normal(0, 0.01, idx.size), index=idx)
    return stand.iloc[365:], pd.DataFrame({"RH": prec, "EV24": evap})


# ── BRO ─────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestBro:
    def test_put_geeft_ligging_maaiveld_en_filters_op_volgorde(self):
        put = bro.lees_put(PUT_XML)
        assert (put["x"], put["y"], put["maaiveld"]) == (26775.0, 400400.0, 3.43)
        assert [f["nummer"] for f in put["filters"]] == [1, 2]
        assert put["filters"][1]["filter_boven"] == -2.87

    def test_onbekende_put_geeft_de_reden_van_de_bro(self):
        with pytest.raises(ValueError, match="bestaat niet"):
            bro.lees_put(AFWIJZING_XML)

    def test_relaties_per_filter(self):
        tekst = json.dumps(
            {"monitoringTubeReferences": [{"tubeNumber": 1, "gldReferences": [{"broId": "GLD1"}, {"broId": "GLD2"}]},
                                          {"tubeNumber": 2, "gldReferences": []}]}
        )
        assert bro.lees_relaties(tekst) == {1: ["GLD1", "GLD2"], 2: []}

    def test_reeks_staat_in_wintertijd_en_beoordeeld_gaat_voor(self):
        s = bro.lees_reeks(REEKS_CSV)
        assert s.index[0] == pd.Timestamp("1995-01-13 12:00")
        assert s.iloc[1] == 1.2  # beoordeeld 1,200 gaat voor voorlopig 1,300

    def test_dagwaarden_middelt_per_dag_en_voegt_dossiers_samen(self):
        s = bro.dagwaarden([bro.lees_reeks(REEKS_CSV), pd.Series(dtype=float)])
        assert list(s.index) == list(pd.to_datetime(["1995-01-13", "1995-01-27"]))
        assert s.iloc[0] == pytest.approx(1.15)

    def test_putnummer_wordt_gecontroleerd(self):
        with pytest.raises(ValueError, match="geen BRO-putnummer"):
            bro.haal_put("B42C0133")


# ── KNMI ────────────────────────────────────────────────────────────────────
@pytest.mark.unit
class TestMeteo:
    def _haal(self, eigen: pd.DataFrame, buur: pd.DataFrame):
        return lambda code, start: eigen if code == 310 else buur

    def test_gat_wordt_gevuld_met_het_buurstation_en_gemeld(self):
        idx = pd.date_range("2000-01-01", periods=400, freq="D")
        eigen = pd.DataFrame({"RH": 2.0, "EV24": 1.0}, index=idx)
        eigen.iloc[100:130, 1] = np.nan
        buur = pd.DataFrame({"RH": 9.0, "EV24": 3.0}, index=idx)
        prec, evap, meldingen = meteo.reeksen_voor(STATIONS_BY_CODE[310], self._haal(eigen, buur))
        assert not prec.isna().any() and not evap.isna().any()
        assert evap.iloc[110] == pytest.approx(0.003)  # mm van de buur, omgerekend naar m
        assert prec.iloc[110] == pytest.approx(0.002)  # eigen neerslag blijft staan
        assert any("30 dagen" in m and "aangevuld" in m for m in meldingen)

    def test_lang_gat_zonder_buren_wordt_niet_verzonnen(self):
        idx = pd.date_range("2000-01-01", periods=400, freq="D")
        eigen = pd.DataFrame({"RH": 2.0, "EV24": 1.0}, index=idx)
        eigen.iloc[50:150, 1] = np.nan
        prec, evap, meldingen = meteo.reeksen_voor(STATIONS_BY_CODE[310], self._haal(eigen, eigen))
        assert prec.index[0] == idx[150]
        assert any("begint op" in m for m in meldingen)

    def test_kort_gat_zonder_buren_wordt_geinterpoleerd_en_gemeld(self):
        idx = pd.date_range("2000-01-01", periods=400, freq="D")
        eigen = pd.DataFrame({"RH": 2.0, "EV24": 1.0}, index=idx)
        eigen.iloc[50:53, 1] = np.nan
        prec, evap, meldingen = meteo.reeksen_voor(STATIONS_BY_CODE[310], self._haal(eigen, eigen))
        assert len(prec) == 400 and not evap.isna().any()
        assert any("geïnterpoleerd" in m for m in meldingen)

    def test_station_zonder_verdamping_is_ongeschikt(self):
        idx = pd.date_range("2000-01-01", periods=10, freq="D")
        alleen_neerslag = pd.DataFrame({"RH": 2.0, "EV24": np.nan}, index=idx)
        with pytest.raises(meteo.GeenGegevens):
            meteo.reeksen_voor(STATIONS_BY_CODE[340], lambda code, start: alleen_neerslag)


# ── project en brug ─────────────────────────────────────────────────────────
@pytest.mark.unit
class TestProject:
    def test_nieuw_project_moet_nog_helemaal_naar_schijf(self, leeg_project):
        w = project.gewijzigd()
        assert w["schrijf"] == ["proef_project.pastastore"] and w["weg"] == []
        assert project.gewijzigd()["schrijf"] == []  # tweede keer: niets nieuws

    def test_alleen_wat_verandert_wordt_gemeld(self, leeg_project):
        stand, _ = _dagreeksen()
        project.gewijzigd()
        STORE.pstore.add_oseries(stand, "put_1", metadata={"x": 1.0, "y": 2.0})
        assert sorted(project.gewijzigd()["schrijf"]) == ["oseries/put_1.pas", "oseries/put_1_meta.pas"]
        project.verwijder_put("put_1")
        assert sorted(project.gewijzigd()["weg"]) == ["oseries/put_1.pas", "oseries/put_1_meta.pas"]

    def test_fit_haalt_stresses_op_en_bewaart_het_model(self, leeg_project, monkeypatch):
        stand, knmi = _dagreeksen()
        monkeypatch.setattr(meteo, "fetch_knmi_daily", lambda code, start: knmi)
        meteo._opgehaald.clear()
        meteo._ongeschikt.clear()
        STORE.pstore.add_oseries(stand, "put_1", metadata={"x": 155000.0, "y": 463000.0, "ground_level": 2.0})
        uit = json.loads(brug.roep("fit", json.dumps({"naam": "put_1"})))["ok"]
        assert uit["gelukt"], uit["melding"]
        assert uit["samenvatting"]["rsq"] > 0.8
        toestand = json.loads(brug.roep("toestand"))["ok"]
        assert toestand["modellen"] == ["put_1"]
        assert {s["soort"] for s in toestand["stresses"]} == {"prec", "evap"}
        assert toestand["putten"][0]["model"] is True
        model = json.loads(brug.roep("model", json.dumps({"naam": "put_1"})))["ok"]
        assert model["heeft_model"] and model["resultaten"]["data"] and model["parameters"]

    def test_statistiek_geeft_gxg_en_grondwatertrap(self, leeg_project):
        stand, _ = _dagreeksen(jaren=12)
        STORE.pstore.add_oseries(stand, "put_1", metadata={"x": 155000.0, "y": 463000.0, "ground_level": 2.0})
        uit = json.loads(brug.roep("statistiek", json.dumps({"namen": ["put_1"]})))["ok"]
        rij = uit["rijen"][0]
        assert rij["mhgl"] > rij["mlgl"] and rij["gt"] != "?" and rij["jaren"] >= 8
        assert uit["foe"]["data"] and uit["regime"]["data"]

    def test_zip_heen_en_terug(self, leeg_project):
        stand, _ = _dagreeksen()
        STORE.pstore.add_oseries(stand, "put_1", metadata={"x": 1.0, "y": 2.0})
        zip_pad = json.loads(brug.roep("maak_zip"))["ok"]["pad"]
        toestand = json.loads(brug.roep("open_zip", json.dumps({"pad": zip_pad})))["ok"]
        assert [p["naam"] for p in toestand["putten"]] == ["put_1"]
        assert toestand["putten"][0]["metingen"] == stand.size

    def test_fout_komt_terug_als_bericht(self, leeg_project):
        uit = json.loads(brug.roep("voeg_put_toe", json.dumps({"gmw": "onzin"})))
        assert "geen BRO-putnummer" in uit["fout"]

    def test_uitkomst_is_altijd_geldige_json(self, leeg_project):
        STORE.pstore.add_oseries(
            pd.Series([1.0, 1.1], index=pd.to_datetime(["2020-01-01", "2020-01-02"])), "kort", metadata={"x": 1.0, "y": 2.0}
        )
        tekst = brug.roep("statistiek", json.dumps({"namen": ["kort"]}))
        assert "NaN" not in tekst
        assert json.loads(tekst)["ok"]["rijen"][0]["mhgl"] is None
