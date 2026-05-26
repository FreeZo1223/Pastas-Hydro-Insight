"""Tests voor incrementeel.py — state, merge, validatie."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest


# ── State persistence ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_laad_delta_state_zonder_bestand_geeft_lege_dict(tmp_path: Path):
    from incrementeel import laad_delta_state

    state = laad_delta_state(tmp_path / "bestaat_niet.json")

    assert state == {}


@pytest.mark.unit
def test_sla_en_laad_delta_state_roundtrip(tmp_path: Path):
    from incrementeel import DeltaState, laad_delta_state, sla_delta_state

    origineel = {
        "Vogels_hist": DeltaState(
            laagnaam="Vogels_hist",
            last_edit_date_unix_ms=1716732000000,
            last_full_fetch_iso="2026-05-15T10:00:00+00:00",
            last_method="incremental",
            validated_count=58260,
        ),
    }
    pad = tmp_path / "state.json"

    sla_delta_state(pad, origineel)
    teruggelezen = laad_delta_state(pad)

    assert "Vogels_hist" in teruggelezen
    assert teruggelezen["Vogels_hist"].validated_count == 58260
    assert teruggelezen["Vogels_hist"].last_method == "incremental"


@pytest.mark.unit
def test_laad_delta_state_skipt_onbekende_velden(tmp_path: Path):
    """Robuust tegen schema-uitbreidingen in oude state-bestanden."""
    import json

    from incrementeel import laad_delta_state

    pad = tmp_path / "state.json"
    pad.write_text(json.dumps({
        "Vogels_hist": {
            "laagnaam": "Vogels_hist",
            "validated_count": 100,
            "OUDE_VELD_DIE_WEG_IS": "negeren",
        }
    }), encoding="utf-8")

    state = laad_delta_state(pad)

    assert state["Vogels_hist"].validated_count == 100


@pytest.mark.unit
def test_sla_delta_state_is_atomair(tmp_path: Path):
    """Tijdelijke .tmp moet weg zijn na succesvolle save."""
    from incrementeel import DeltaState, sla_delta_state

    pad = tmp_path / "state.json"
    sla_delta_state(pad, {"x": DeltaState(laagnaam="x")})

    assert pad.exists()
    assert not pad.with_suffix(pad.suffix + ".tmp").exists()


# ── Merge logica ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Geef DuckDB-connectie + tmp-pad terug."""
    pad = str(tmp_path / "test.duckdb")
    con = duckdb.connect(pad)
    yield con
    con.close()


@pytest.mark.unit
def test_merge_voegt_nieuwe_rijen_toe(db):
    from incrementeel import merge_dataframe

    db.execute("CREATE TABLE t (global_id VARCHAR, waarde INTEGER)")
    db.execute("INSERT INTO t VALUES ('a', 1), ('b', 2)")

    nieuwe = pd.DataFrame({"global_id": ["c", "d"], "waarde": [3, 4]})
    vervangen, nieuw = merge_dataframe(db, "t", nieuwe, "global_id")

    assert vervangen == 0
    assert nieuw == 2
    assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 4


@pytest.mark.unit
def test_merge_vervangt_bestaande_rijen(db):
    from incrementeel import merge_dataframe

    db.execute("CREATE TABLE t (global_id VARCHAR, waarde INTEGER)")
    db.execute("INSERT INTO t VALUES ('a', 1), ('b', 2)")

    nieuwe = pd.DataFrame({"global_id": ["a", "b"], "waarde": [99, 88]})
    vervangen, nieuw = merge_dataframe(db, "t", nieuwe, "global_id")

    assert vervangen == 2
    assert nieuw == 0
    assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    assert db.execute("SELECT waarde FROM t WHERE global_id='a'").fetchone()[0] == 99


@pytest.mark.unit
def test_merge_mixed_nieuw_en_update(db):
    from incrementeel import merge_dataframe

    db.execute("CREATE TABLE t (global_id VARCHAR, waarde INTEGER)")
    db.execute("INSERT INTO t VALUES ('a', 1), ('b', 2)")

    nieuwe = pd.DataFrame({
        "global_id": ["b", "c", "d"],  # b = update, c+d = nieuw
        "waarde":    [22, 3, 4],
    })
    vervangen, nieuw = merge_dataframe(db, "t", nieuwe, "global_id")

    assert vervangen == 1
    assert nieuw == 2
    assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 4
    assert db.execute("SELECT waarde FROM t WHERE global_id='b'").fetchone()[0] == 22


@pytest.mark.unit
def test_merge_lege_dataframe_doet_niets(db):
    from incrementeel import merge_dataframe

    db.execute("CREATE TABLE t (global_id VARCHAR, waarde INTEGER)")
    db.execute("INSERT INTO t VALUES ('a', 1)")

    vervangen, nieuw = merge_dataframe(db, "t", pd.DataFrame(), "global_id")

    assert (vervangen, nieuw) == (0, 0)
    assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


@pytest.mark.unit
def test_merge_faalt_zonder_pk_kolom(db):
    from incrementeel import merge_dataframe

    db.execute("CREATE TABLE t (global_id VARCHAR, waarde INTEGER)")
    nieuwe = pd.DataFrame({"andere_kolom": ["a", "b"], "waarde": [1, 2]})

    with pytest.raises(ValueError, match="ontbreekt"):
        merge_dataframe(db, "t", nieuwe, "global_id")


# ── Validatie ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_validatie_signaleert_count_mismatch(db):
    from incrementeel import valideer_post_merge

    db.execute("CREATE TABLE t (global_id VARCHAR)")
    db.execute("INSERT INTO t VALUES ('a'), ('b'), ('c')")

    res = valideer_post_merge(db, "t", "global_id", agol_count=5)

    assert not res.geslaagd
    assert "count-mismatch" in res.melding
    assert res.count_lokaal == 3
    assert res.count_agol == 5


@pytest.mark.unit
def test_validatie_signaleert_duplicate_pk(db):
    from incrementeel import valideer_post_merge

    db.execute("CREATE TABLE t (global_id VARCHAR)")
    db.execute("INSERT INTO t VALUES ('a'), ('a'), ('b')")

    res = valideer_post_merge(db, "t", "global_id", agol_count=3)

    assert not res.geslaagd
    assert "duplicate" in res.melding.lower()
    assert res.pk_duplicaten == 1


@pytest.mark.unit
def test_validatie_signaleert_ontbrekende_sample(db):
    from incrementeel import valideer_post_merge

    db.execute("CREATE TABLE t (global_id VARCHAR)")
    db.execute("INSERT INTO t VALUES ('a'), ('b'), ('c')")

    # AGOL claimt PK 'x' bestaat — die is er lokaal niet
    res = valideer_post_merge(db, "t", "global_id", agol_count=3,
                              sample_pks_agol={"a", "x"})

    assert not res.geslaagd
    assert res.sample_mismatches == 1


@pytest.mark.unit
def test_validatie_geslaagd_bij_perfecte_match(db):
    from incrementeel import valideer_post_merge

    db.execute("CREATE TABLE t (global_id VARCHAR)")
    db.execute("INSERT INTO t VALUES ('a'), ('b'), ('c')")

    res = valideer_post_merge(db, "t", "global_id", agol_count=3,
                              sample_pks_agol={"a", "c"})

    assert res.geslaagd
    assert res.melding == "OK"


# ── Utilities ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_nieuwste_edit_date_uit_dataframe():
    from incrementeel import nieuwste_edit_date_ms

    df = pd.DataFrame({"EditDate": [1700000000000, 1716732000000, 1710000000000]})
    assert nieuwste_edit_date_ms(df, "EditDate") == 1716732000000


@pytest.mark.unit
def test_nieuwste_edit_date_leeg_of_missend():
    from incrementeel import nieuwste_edit_date_ms

    assert nieuwste_edit_date_ms(pd.DataFrame(), "EditDate") is None
    assert nieuwste_edit_date_ms(pd.DataFrame({"x": [1]}), "EditDate") is None


@pytest.mark.unit
def test_sample_pks_deterministisch_met_seed():
    from incrementeel import kies_sample_pks

    pks = list(range(100))
    a = kies_sample_pks(pks, k=5, seed=42)
    b = kies_sample_pks(pks, k=5, seed=42)

    assert a == b
    assert len(a) == 5


@pytest.mark.unit
def test_sample_kleiner_dan_k_geeft_alles_terug():
    from incrementeel import kies_sample_pks

    assert kies_sample_pks([1, 2], k=5) == {1, 2}
    assert kies_sample_pks([], k=5) == set()
