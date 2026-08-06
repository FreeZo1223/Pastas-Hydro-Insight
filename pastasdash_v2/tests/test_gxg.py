"""Tests voor de GxG-berekening in compute/timeseries.py.

Kern van deze suite: de GxG moet gelijk zijn aan ``pastas.stats`` en mag
onvolledige hydrologische jaren niet meerekenen. Een eerdere eigen
implementatie deed dat wel en gaf daardoor een ruim een decimeter te hoge
GLG — wat doorwerkt in de grondwatertrap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pastas as ps
import pytest

from pastasdash_v2.core import timeseries as tsmod


def _synthetische_reeks(jaren: int = 12, start: str = "1990-04-01") -> pd.Series:
    """Tweewekelijkse reeks (14e/28e) met een nette sinusvormige jaargang."""
    dates = pd.date_range(start=start, periods=jaren * 12, freq="MS")
    idx = pd.DatetimeIndex(
        sorted([d.replace(day=14) for d in dates] + [d.replace(day=28) for d in dates])
    )
    # zomer laag, winter hoog
    doy = idx.dayofyear.to_numpy()
    waarden = 2.0 + 0.4 * np.cos(2 * np.pi * doy / 365.25)
    return pd.Series(waarden, index=idx)


def _gxg_op(series: pd.Series) -> dict:
    """Roep de ongecachete gxg() aan met een vaste reeks."""
    origineel = tsmod.get_oseries
    tsmod.get_oseries = lambda name: series
    try:
        return tsmod.gxg.__wrapped__("teststore", "peilbuis")
    finally:
        tsmod.get_oseries = origineel


@pytest.mark.unit
class TestGxGKomtOvereenMetPastas:
    """De dashboardwaarde mag niet afwijken van de referentie-implementatie."""

    def test_ghg_glg_gvg_gelijk_aan_pastas(self):
        s = _synthetische_reeks()
        resultaat = _gxg_op(s)
        assert resultaat["GHG"] == pytest.approx(ps.stats.ghg(s), abs=1e-9)
        assert resultaat["GLG"] == pytest.approx(ps.stats.glg(s), abs=1e-9)
        assert resultaat["GVG"] == pytest.approx(ps.stats.gvg(s), abs=1e-9)

    def test_ghg_ligt_boven_glg(self):
        resultaat = _gxg_op(_synthetische_reeks())
        assert resultaat["GHG"] > resultaat["GLG"]


@pytest.mark.unit
class TestOnvolledigeJarenTellenNietMee:
    """Regressietest op de bug die de GLG omhoog trok."""

    def test_half_winterjaar_vooraf_verandert_glg_niet(self):
        """Een aangeplakt half winterjaar heeft geen zomer-laagstanden.

        Meerekenen zou de GLG kunstmatig verhogen; pastas laat zo'n jaar
        vallen, dus de GLG hoort onveranderd te blijven.
        """
        volledig = _synthetische_reeks(jaren=12, start="1990-04-01")
        basis = _gxg_op(volledig)

        # drie wintermaanden vóór de reeks plakken (jan–mrt, hoge standen)
        winter_idx = pd.DatetimeIndex(
            [pd.Timestamp("1990-01-14"), pd.Timestamp("1990-01-28"),
             pd.Timestamp("1990-02-14"), pd.Timestamp("1990-02-28"),
             pd.Timestamp("1990-03-14"), pd.Timestamp("1990-03-28")]
        )
        winter = pd.Series(np.full(len(winter_idx), 2.4), index=winter_idx)
        met_stub = pd.concat([winter, volledig]).sort_index()

        resultaat = _gxg_op(met_stub)
        assert resultaat["GLG"] == pytest.approx(basis["GLG"], abs=1e-9)


@pytest.mark.unit
class TestTeKorteReeks:
    """Liever geen waarde dan een onbetrouwbare waarde."""

    def test_drie_jaar_geeft_nan(self):
        resultaat = _gxg_op(_synthetische_reeks(jaren=3))
        assert np.isnan(resultaat["GHG"])
        assert np.isnan(resultaat["GLG"])

    def test_lege_reeks_geeft_nan_en_nul_jaren(self):
        resultaat = _gxg_op(pd.Series(dtype=float))
        assert np.isnan(resultaat["GLG"])
        assert resultaat["n_years"] == 0

    def test_n_years_verklaart_lege_uitkomst(self):
        """n_years moet laten zien dat er te weinig jaren zijn, niet nul."""
        resultaat = _gxg_op(_synthetische_reeks(jaren=3))
        assert 0 < resultaat["n_years"] < 8

    def test_n_years_telt_volledige_reeks(self):
        resultaat = _gxg_op(_synthetische_reeks(jaren=12))
        assert resultaat["n_years"] >= 8
