"""Test voor het inlezen van KNMI-daggegevens via het directe adres.

Aanleiding: het KNMI zet de kolomnamen in een commentaarregel. De lezer
gooide alle commentaarregels weg en zag daardoor de eerste dag als kopregel,
wat eindigde in ``KeyError: 'datum'``. Zolang hydropandas het ophalen deed
viel dat niet op; zonder hydropandas werkte het ophalen niet.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pastasdash_v2.core.knmi import _lees_knmi_tekst

ANTWOORD = """# DEZE GEGEVENS MOGEN VRIJ WORDEN GEBRUIKT MITS DE VOLGENDE BRONVERMELDING WORDT GEGEVEN:
# STN         LON(east)   LAT(north)  ALT(m)      NAME
# 310         3.596       51.442      8.00        Vlissingen
# RH        : Etmaalsom van de neerslag (in 0.1 mm) (-1 voor <0.05 mm)
# EV24      : Referentiegewasverdamping (Makkink) (in 0.1 mm)
# STN,YYYYMMDD,   RH, EV24
  310,20240101,   58,    4
  310,20240102,   -1,    1
  310,20240103,     ,    3
"""


@pytest.mark.unit
def test_leest_dagwaarden_in_mm():
    df = _lees_knmi_tekst(ANTWOORD)
    assert list(df.columns) == ["RH", "EV24"]
    assert list(df.index) == list(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    assert df.loc["2024-01-01", "RH"] == pytest.approx(5.8)
    assert df.loc["2024-01-01", "EV24"] == pytest.approx(0.4)


@pytest.mark.unit
def test_spoor_neerslag_wordt_nul_en_leeg_blijft_leeg():
    df = _lees_knmi_tekst(ANTWOORD)
    assert df.loc["2024-01-02", "RH"] == 0.0
    assert pd.isna(df.loc["2024-01-03", "RH"])
