"""Tests voor checkpoint state-management in agol_naar_duckdb_v2.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_checkpoint(tmp_path, monkeypatch):
    """Patch CHECKPOINT_PAD naar tmp-bestand zodat tests elkaar niet beïnvloeden."""
    pad = tmp_path / "checkpoint.json"
    import agol_naar_duckdb_v2 as mod
    monkeypatch.setattr(mod, "CHECKPOINT_PAD", str(pad))
    return pad


@pytest.mark.unit
def test_laad_checkpoint_zonder_bestand_geeft_lege_state(tmp_checkpoint):
    from agol_naar_duckdb_v2 import laad_checkpoint

    state = laad_checkpoint()

    assert state["voltooid"] == {}
    assert state["partieel"] == {}
    assert "gestart_op" in state


@pytest.mark.unit
def test_laad_checkpoint_migreert_oude_deels_keys(tmp_checkpoint):
    """Oude checkpoints hebben _deels-keys in voltooid — moeten naar partieel."""
    from agol_naar_duckdb_v2 import laad_checkpoint

    oud = {
        "gestart_op": "2026-05-01T10:00:00",
        "voltooid": {
            "Vogels_actueel": {"rijen": 281, "tijdstip": "2026-05-01T10:05:00"},
            "Vleermuizen_hist_deels": {"rijen": 15000, "tijdstip": "2026-05-01T10:30:00"},
        },
    }
    tmp_checkpoint.write_text(json.dumps(oud), encoding="utf-8")

    state = laad_checkpoint()

    assert "Vogels_actueel" in state["voltooid"]
    assert "Vleermuizen_hist_deels" not in state["voltooid"], \
        "_deels keys mogen niet meer in voltooid voorkomen"
    assert "Vleermuizen_hist" in state["partieel"], \
        "Naam zonder _deels suffix moet naar partieel"
    assert state["partieel"]["Vleermuizen_hist"]["rijen"] == 15000


@pytest.mark.unit
def test_sla_checkpoint_op_ruimt_partieel_status_op(tmp_checkpoint):
    """Als een laag eerder partieel was en nu volledig lukt, verdwijnt 'partieel'."""
    from agol_naar_duckdb_v2 import sla_checkpoint_op, sla_partieel_op

    state = {"voltooid": {}, "partieel": {}}

    sla_partieel_op(state, "Vleermuizen_hist", 15000)
    assert "Vleermuizen_hist" in state["partieel"]

    sla_checkpoint_op(state, "Vleermuizen_hist", 35658)
    assert "Vleermuizen_hist" in state["voltooid"]
    assert "Vleermuizen_hist" not in state["partieel"], \
        "Bij succesvolle voltooiing moet partieel-status verdwijnen"


@pytest.mark.unit
def test_sla_partieel_op_blokkeert_hervat_niet(tmp_checkpoint):
    """Partieel mag niet als 'voltooid' tellen — anders worden rijen overgeslagen."""
    from agol_naar_duckdb_v2 import sla_partieel_op

    state = {"voltooid": {}, "partieel": {}}
    sla_partieel_op(state, "Vleermuizen_hist", 15000)

    assert "Vleermuizen_hist" not in state["voltooid"]
    assert state["partieel"]["Vleermuizen_hist"]["rijen"] == 15000
