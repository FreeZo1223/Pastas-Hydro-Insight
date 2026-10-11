"""Test dat een model fitten op dagreeksen werkt.

Aanleiding: met pastas 1.11 en pandas 3 gaf een fit op dagwaarden
``ValueError: freq of D not supported``. Er was geen test die de fit zelf
uitvoerde, dus dat bleef onopgemerkt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pastastore as pst
import pytest

from pastasdash_v2.core import fitting
from pastasdash_v2.core.fitting import FitOptions, fit_model
from pastasdash_v2.core.store import STORE


def _dagreeksen(jaren: int = 6) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Neerslag en verdamping per dag, en een stijghoogte die erop reageert."""
    rng = np.random.default_rng(1)
    idx = pd.date_range("2010-01-01", periods=jaren * 365, freq="D")
    prec = pd.Series(rng.gamma(0.4, 0.005, idx.size), index=idx, name="prec")
    evap = pd.Series(
        0.0015 * (1 - np.cos(2 * np.pi * idx.dayofyear / 365.25)), index=idx, name="evap"
    )
    aanvulling = (prec - evap).to_numpy()
    respons = np.exp(-np.arange(200) / 40.0)
    stand = 1.0 + 4.0 * np.convolve(aanvulling, respons)[: idx.size]
    stand = pd.Series(stand + rng.normal(0, 0.01, idx.size), index=idx, name="put")
    return stand.iloc[365:], prec, evap


@pytest.fixture
def store_met_put(monkeypatch):
    """Zet een store in het geheugen neer, zonder de instellingen op schijf te raken."""
    stand, prec, evap = _dagreeksen()
    pstore = pst.PastaStore(pst.DictConnector("fit_test"))
    pstore.add_oseries(stand, "put", metadata={"x": 0.0, "y": 0.0})
    pstore.add_stress(prec, "neerslag_KNMI", kind="prec", metadata={"x": 0.0, "y": 0.0})
    pstore.add_stress(evap, "verdamping_KNMI", kind="evap", metadata={"x": 0.0, "y": 0.0})
    monkeypatch.setattr(STORE, "_pstore", pstore)
    monkeypatch.setattr(STORE, "_store_key", "test:fit")
    monkeypatch.setattr(fitting, "invalidate_store", lambda sleutel: 0)
    return pstore


@pytest.mark.unit
def test_fit_op_dagreeksen_slaagt(store_met_put):
    gelukt, melding, ml = fit_model("put", FitOptions())
    assert gelukt, melding
    assert ml.stats.rsq() > 0.8
    assert "put" in store_met_put.model_names
