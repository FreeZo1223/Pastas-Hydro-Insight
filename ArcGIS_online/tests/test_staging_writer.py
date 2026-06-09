"""
Tests voor staging-aanmaak en duckdb_writer.py subprocess-logica.
Alle tests zijn unit-level — geen netwerk, geen echte AGOL.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_data() -> dict[str, pd.DataFrame]:
    """Kleine dataset die een echte soortgroep nabootst."""
    return {
        "Vogels": pd.DataFrame({
            "global_id":   ["v1", "v2", "v3"],
            "soort":       ["Koolmees", "Vink", "Roodborst"],
            "datum_bron":  ["2026-01-01", "2026-02-01", "onbekend"],
            "_bron_type":  ["agol_actueel", "agol_actueel", "parquet"],
        }),
        "Reptielen": pd.DataFrame({
            "global_id":  ["r1", "r2"],
            "soort":      ["Hazelworm", "Ringslang"],
            "datum_bron": ["2026-03-01", "2026-04-01"],
            "_bron_type": ["agol_actueel", "agol_actueel"],
        }),
    }


@pytest.fixture
def staging_dir(tmp_path: Path, sample_data) -> Path:
    """Aangemaakt staging-dir met manifest + parquets."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from agol_naar_duckdb_v2 import sla_staging_op, STAGING_ROOT
    import agol_naar_duckdb_v2 as mod

    # Override STAGING_ROOT naar tmp_path zodat we niet in echte data schrijven
    original = mod.STAGING_ROOT
    mod.STAGING_ROOT = tmp_path / "staging"
    try:
        pad = sla_staging_op(sample_data, "20260609_1000")
    finally:
        mod.STAGING_ROOT = original
    return pad


# ── Staging aanmaken ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_sla_staging_op_maakt_parquets(staging_dir: Path, sample_data):
    """Elk soortgroep krijgt een parquet-bestand."""
    parquets = list(staging_dir.glob("*.parquet"))
    assert len(parquets) == len(sample_data)


@pytest.mark.unit
def test_sla_staging_op_schrijft_manifest(staging_dir: Path, sample_data):
    """Manifest bevat alle tabellen met correcte rij-aantallen."""
    manifest = json.loads((staging_dir / "manifest.json").read_text())
    tabellen = manifest["tabellen"]

    assert "waarnemingen_vogels" in tabellen
    assert "waarnemingen_reptielen" in tabellen
    assert tabellen["waarnemingen_vogels"]["verwacht_rijen"] == 3
    assert tabellen["waarnemingen_reptielen"]["verwacht_rijen"] == 2


@pytest.mark.unit
def test_sla_staging_op_tabel_naam_normalisatie(tmp_path: Path):
    """Soortgroep-namen met accenten worden correct genormaliseerd."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import agol_naar_duckdb_v2 as mod

    data = {
        "Amfibieën": pd.DataFrame({"global_id": ["a1"], "datum_bron": ["2026-01-01"], "_bron_type": ["agol"]}),
    }
    original = mod.STAGING_ROOT
    mod.STAGING_ROOT = tmp_path / "staging"
    try:
        pad = mod.sla_staging_op(data, "test_run")
    finally:
        mod.STAGING_ROOT = original

    manifest = json.loads((pad / "manifest.json").read_text())
    # ë → e
    assert "waarnemingen_amfibieen" in manifest["tabellen"]


# ── Writer logica ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_writer_schrijft_tabellen_naar_duckdb(staging_dir: Path, tmp_path: Path):
    """Writer leest staging en schrijft naar verse DuckDB."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from duckdb_writer import schrijf_staging_naar_duckdb

    db_pad = str(tmp_path / "test.duckdb")
    geslaagd = schrijf_staging_naar_duckdb(staging_dir, db_pad)

    assert geslaagd, "Writer moet True teruggeven bij succes"

    with duckdb.connect(db_pad, read_only=True) as con:
        tabs = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name LIKE 'waarnemingen_%'"
        ).fetchall()}
    assert "waarnemingen_vogels" in tabs
    assert "waarnemingen_reptielen" in tabs


@pytest.mark.unit
def test_writer_verifieert_rij_aantallen(staging_dir: Path, tmp_path: Path):
    """Geschreven rij-aantallen moeten overeenkomen met manifest."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from duckdb_writer import schrijf_staging_naar_duckdb

    db_pad = str(tmp_path / "test.duckdb")
    schrijf_staging_naar_duckdb(staging_dir, db_pad)

    with duckdb.connect(db_pad, read_only=True) as con:
        n_vogels = con.execute(
            "SELECT COUNT(*) FROM waarnemingen_vogels"
        ).fetchone()[0]
        n_reptielen = con.execute(
            "SELECT COUNT(*) FROM waarnemingen_reptielen"
        ).fetchone()[0]

    assert n_vogels == 3
    assert n_reptielen == 2


@pytest.mark.unit
def test_writer_ruimt_staging_op_na_succes(staging_dir: Path, tmp_path: Path):
    """Staging-dir moet worden verwijderd na succesvolle write."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from duckdb_writer import schrijf_staging_naar_duckdb, ruim_staging_op

    db_pad = str(tmp_path / "test.duckdb")
    geslaagd = schrijf_staging_naar_duckdb(staging_dir, db_pad)
    assert geslaagd

    ruim_staging_op(staging_dir)
    assert not staging_dir.exists(), "Staging moet weg zijn na opruimen"


@pytest.mark.unit
def test_writer_geeft_false_bij_ontbrekend_parquet(staging_dir: Path, tmp_path: Path):
    """Als een parquet ontbreekt, moet writer False retourneren."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from duckdb_writer import schrijf_staging_naar_duckdb

    # Verwijder één parquet zodat het manifest niet klopt
    for p in staging_dir.glob("*.parquet"):
        p.unlink()
        break

    db_pad = str(tmp_path / "test.duckdb")
    geslaagd = schrijf_staging_naar_duckdb(staging_dir, db_pad)

    assert not geslaagd, "Writer moet False geven bij ontbrekend parquet"


@pytest.mark.unit
def test_writer_laat_staging_staan_bij_fout(staging_dir: Path, tmp_path: Path):
    """Staging moet bewaard blijven als writer faalt (voor diagnose/retry)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from duckdb_writer import schrijf_staging_naar_duckdb

    # Corrupteer manifest zodat writer faalt
    manifest_pad = staging_dir / "manifest.json"
    manifest = json.loads(manifest_pad.read_text())
    for tabel in manifest["tabellen"]:
        manifest["tabellen"][tabel]["verwacht_rijen"] = 999_999  # onmogelijk hoog
    manifest_pad.write_text(json.dumps(manifest))

    db_pad = str(tmp_path / "test.duckdb")
    geslaagd = schrijf_staging_naar_duckdb(staging_dir, db_pad)

    assert not geslaagd
    assert staging_dir.exists(), "Staging moet bewaard blijven bij fout"


# ── Cleanup ───────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_ruim_oude_stagings_op(tmp_path: Path):
    """Dirs ouder dan max_leeftijd_uren worden verwijderd."""
    import sys, os, time as tmod
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import agol_naar_duckdb_v2 as mod

    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    oude_dir = staging_root / "20260601_1000"
    oude_dir.mkdir()

    # Zet mtime ver in het verleden
    oud_tijdstip = 0.0  # epoch = 1 jan 1970
    os.utime(oude_dir, (oud_tijdstip, oud_tijdstip))

    original = mod.STAGING_ROOT
    mod.STAGING_ROOT = staging_root
    try:
        mod.ruim_oude_stagings_op(max_leeftijd_uren=1)
    finally:
        mod.STAGING_ROOT = original

    assert not oude_dir.exists(), "Oude staging moet verwijderd zijn"


@pytest.mark.unit
def test_ruim_oude_stagings_bewaart_recente(tmp_path: Path):
    """Recente staging-dirs moeten NIET worden verwijderd."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import agol_naar_duckdb_v2 as mod

    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    nieuwe_dir = staging_root / "20260609_1000"
    nieuwe_dir.mkdir()  # mtime = nu

    original = mod.STAGING_ROOT
    mod.STAGING_ROOT = staging_root
    try:
        mod.ruim_oude_stagings_op(max_leeftijd_uren=48)
    finally:
        mod.STAGING_ROOT = original

    assert nieuwe_dir.exists(), "Recente staging mag niet verwijderd worden"
