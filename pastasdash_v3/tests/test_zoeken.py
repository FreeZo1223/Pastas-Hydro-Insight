"""Putten zoeken in een projectgebied: de module zelf en het Cowork-script.

Zonder netwerk: de BRO wordt nagebootst, en het script wordt "offline"
gezet met een proxy die niet bestaat.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pastasdash_v3 import zoeken

V3 = Path(__file__).resolve().parents[1]
SKILL = V3 / "dist" / "eelerwoude-pastasdash" / "scripts"
GEBIEDSVERKENNER_GEO_IO = V3.parents[2] / "Tools" / "gebiedsverkenner" / "cowork" / "geo_io.py"

# Een vierkant van ongeveer 1 bij 1 km bij Wilnis, met een gat in het midden.
VIERKANT = [[4.890, 52.190], [4.9046, 52.190], [4.9046, 52.199], [4.890, 52.199], [4.890, 52.190]]
GAT = [[4.896, 52.194], [4.898, 52.194], [4.898, 52.195], [4.896, 52.195], [4.896, 52.194]]
GEBIED = {"type": "Polygon", "coordinates": [VIERKANT, GAT]}


def antwoord(*putten: tuple[str, float, float, str]) -> str:
    """Een antwoord zoals de BRO het geeft, met alleen wat de module leest."""
    leden = "".join(
        f'<GMW_C><brocom:broId>{i}</brocom:broId><brocom:standardizedLocation srsName="urn:ogc:def:crs:EPSG::4258">'
        f"<gml:pos>{lat} {lon}</gml:pos></brocom:standardizedLocation><removed>{weg}</removed></GMW_C>"
        for i, lat, lon, weg in putten
    )
    return ('<dispatchCharacteristicsResponse xmlns="http://www.broservices.nl/xsd/dsgmw/1.1" '
            'xmlns:brocom="http://www.broservices.nl/xsd/brocommon/3.0" xmlns:gml="http://www.opengis.net/gml/3.2">'
            f"<brocom:responseType>dispatch</brocom:responseType><dispatchDocument>{leden}</dispatchDocument>"
            "</dispatchCharacteristicsResponse>")


WEIGERING = ('<dispatchCharacteristicsResponse xmlns:brocom="http://www.broservices.nl/xsd/brocommon/3">'
             "<brocom:responseType>rejection</brocom:responseType><brocom:rejectionReason>Het aantal objecten is "
             "groter dan 2000. Pas de kenmerken van uw verzoek tot levering aan.</brocom:rejectionReason>"
             "</dispatchCharacteristicsResponse>")


class TestGebied:
    def test_binnen_is_nul_en_in_het_gat_niet(self):
        assert zoeken.afstand_tot_gebied(52.192, 4.893, [GEBIED["coordinates"]]) == 0
        assert zoeken.afstand_tot_gebied(52.1945, 4.897, [GEBIED["coordinates"]]) > 0

    def test_afstand_buiten_klopt_op_de_meter(self):
        # 0,001 graad ten noorden van de rand is 111 m.
        assert zoeken.afstand_tot_gebied(52.200, 4.895, [GEBIED["coordinates"]]) == pytest.approx(111.3, abs=1)

    def test_featurecollection_en_multipolygon_worden_gelezen(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": GEBIED},
            {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[VIERKANT], [VIERKANT]]}},
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": VIERKANT}}]}
        assert len(zoeken.vlakken(fc)) == 3

    def test_lijn_is_geen_zoekgebied(self):
        with pytest.raises(ValueError, match="geen vlakken"):
            zoeken.zoek_putten("x", {"type": "LineString", "coordinates": VIERKANT})


class TestZoeken:
    def test_alleen_putten_in_het_gebied_plus_marge(self):
        vragen = []

        def bro(url, body):
            vragen.append(body)
            return antwoord(("GMW000000000003", 52.192, 4.893, "nee"),       # binnen
                            ("GMW000000000002", 52.1995, 4.895, "ja"),       # 56 m buiten de noordrand
                            ("GMW000000000001", 52.205, 4.895, "nee"),       # 670 m buiten
                            ("GMW000000000004", 52.1945, 4.897, "nee"))      # in het gat: 55 m van de gatrand
        gevonden = zoeken.zoek_putten("https://bro", GEBIED, 100, haal=bro)
        assert [p["id"] for p in gevonden] == ["GMW000000000002", "GMW000000000003", "GMW000000000004"]
        assert gevonden[0]["verwijderd"] and gevonden[0]["afstand_m"] == pytest.approx(56, abs=2)
        # De rechthoek is met de marge verruimd: 100 m is 0,0009 graad breedte.
        hoek = vragen[0]["area"]["boundingBox"]
        assert hoek["upperCorner"]["lat"] == pytest.approx(52.199 + 0.0009, abs=1e-4)
        assert zoeken.zoek_putten("https://bro", GEBIED, 0, haal=bro)[0]["id"] == "GMW000000000003"

    def test_meer_dan_2000_putten_is_te_groot(self):
        with pytest.raises(zoeken.TeGroot):
            zoeken.zoek_putten("https://bro", GEBIED, haal=lambda url, body: WEIGERING)


def test_geo_io_is_gelijk_aan_die_van_de_gebiedsverkenner():
    if not GEBIEDSVERKENNER_GEO_IO.exists():
        pytest.skip("de gebiedsverkenner staat niet op deze computer")
    assert (V3 / "cowork" / "geo_io.py").read_bytes() == GEBIEDSVERKENNER_GEO_IO.read_bytes(), (
        "cowork/geo_io.py wijkt af van de gebiedsverkenner; kopieer de nieuwste versie")


@pytest.mark.skipif(not SKILL.exists(), reason="eerst bouw.py draaien")
class TestScript:
    def maak(self, tmp_path, *args, offline=True):
        omgeving = dict(os.environ)
        if offline:
            omgeving.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")
        r = subprocess.run([sys.executable, str(SKILL / "maak_pastasdash.py"), "--out", str(tmp_path / "pd.html"), *args],
                           capture_output=True, text=True, encoding="utf-8", env=omgeving)
        return json.loads(r.stdout)

    def staat(self, tmp_path) -> dict:
        html = (tmp_path / "pd.html").read_text(encoding="utf-8")
        begin = html.index('<script id="pd-staat" type="application/json">') + len('<script id="pd-staat" type="application/json">')
        return json.loads(html[begin:html.index("</script>", begin)])

    def test_zonder_internet_zoekt_de_pagina(self, tmp_path):
        grens = tmp_path / "grens.geojson"
        grens.write_text(json.dumps({"type": "Feature", "geometry": GEBIED}), encoding="utf-8")
        uit = self.maak(tmp_path, "--grens", str(grens), "--marge", "250", "--titel", "Wilnis", "--putten", "GMW000000069526")
        assert uit["ok"] and uit["gebied"]["gezocht_door"] == "pagina"
        staat = self.staat(tmp_path)
        assert staat["putten"] == ["GMW000000069526"]
        assert staat["zoekgebied"]["marge_m"] == 250 and staat["zoekgebied"]["naam"] == "Wilnis"
        # Heen via RD en terug: de hoeken liggen op een paar centimeter na op dezelfde plek.
        hoek = staat["zoekgebied"]["gebied"]["coordinates"][0][0][0]
        assert hoek == pytest.approx(VIERKANT[0], abs=1e-6)

    def test_grens_van_lijnen_wordt_geweigerd(self, tmp_path):
        grens = tmp_path / "lijn.geojson"
        grens.write_text(json.dumps({"type": "LineString", "coordinates": VIERKANT}), encoding="utf-8")
        uit = self.maak(tmp_path, "--grens", str(grens))
        assert not uit["ok"] and "vlakken" in uit["melding"]

    def test_grens_buiten_nederland_wordt_geweigerd(self, tmp_path):
        grens = tmp_path / "ver.geojson"
        grens.write_text(json.dumps({"type": "Polygon", "coordinates": [[[x + 20, y] for x, y in VIERKANT]]}), encoding="utf-8")
        uit = self.maak(tmp_path, "--grens", str(grens))
        assert not uit["ok"] and "buiten Nederland" in uit["melding"]

    @pytest.mark.skipif(os.environ.get("PASTASDASH_GEEN_NETWERK") == "1", reason="zonder netwerk")
    def test_met_internet_zoekt_cowork_zelf(self, tmp_path):
        grens = tmp_path / "grens.geojson"
        grens.write_text(json.dumps({"type": "Feature", "geometry": GEBIED}), encoding="utf-8")
        uit = self.maak(tmp_path, "--grens", str(grens), offline=False)
        assert uit["ok"] and uit["gebied"]["gezocht_door"] == "cowork", uit
        assert uit["aantal_putten"] == uit["gebied"]["gevonden"] > 0
        assert "zoekgebied" not in self.staat(tmp_path)
