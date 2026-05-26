"""End-to-end tests voor _schrijf_df_naar_tabel — beide paden (small + chunked)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest


@pytest.fixture
def db_pad(tmp_path: Path) -> str:
    """Tijdelijk DuckDB-bestand per test."""
    return str(tmp_path / "test.duckdb")


@pytest.mark.unit
def test_small_path_zonder_chunking(db_pad: str):
    """DataFrames onder de drempel gebruiken het oude één-parquet pad."""
    from agol_naar_duckdb_v2 import _schrijf_df_naar_tabel

    df = pd.DataFrame({"id": range(100), "naam": [f"row_{i}" for i in range(100)]})

    with duckdb.connect(db_pad) as con:
        _schrijf_df_naar_tabel(con, df, "test_klein", db_pad)
        telling = con.execute("SELECT COUNT(*) FROM test_klein").fetchone()[0]

    assert telling == 100


@pytest.mark.unit
def test_chunked_path_telt_correct_op(db_pad: str, monkeypatch):
    """Boven de drempel: chunks samen moeten exact alle rijen bevatten."""
    import agol_naar_duckdb_v2 as mod

    monkeypatch.setattr(mod, "CHUNKED_WRITE_THRESHOLD", 50)
    monkeypatch.setattr(mod, "CHUNK_RIJEN", 20)

    n = 137  # bewust niet deelbaar door chunk-grootte — laatste chunk is partial
    df = pd.DataFrame({
        "id":   range(n),
        "naam": [f"row_{i}" for i in range(n)],
        "waarde": [i * 1.5 for i in range(n)],
    })

    with duckdb.connect(db_pad) as con:
        mod._schrijf_df_naar_tabel(con, df, "test_chunked", db_pad)
        telling = con.execute("SELECT COUNT(*) FROM test_chunked").fetchone()[0]
        # Inhoud-check: alle id's moeten present zijn, geen duplicaten
        unieke_ids = con.execute("SELECT COUNT(DISTINCT id) FROM test_chunked").fetchone()[0]
        max_id = con.execute("SELECT MAX(id) FROM test_chunked").fetchone()[0]

    assert telling == n
    assert unieke_ids == n
    assert max_id == n - 1


@pytest.mark.unit
def test_chunked_pad_ruimt_tijdelijke_parquets_op(db_pad: str, monkeypatch, tmp_path):
    """Na een succesvolle chunked write mogen er geen _temp_*.parquet bestanden achterblijven."""
    import agol_naar_duckdb_v2 as mod

    monkeypatch.setattr(mod, "CHUNKED_WRITE_THRESHOLD", 50)
    monkeypatch.setattr(mod, "CHUNK_RIJEN", 20)

    df = pd.DataFrame({"id": range(100)})

    with duckdb.connect(db_pad) as con:
        mod._schrijf_df_naar_tabel(con, df, "test_cleanup", db_pad)

    rest = list(tmp_path.glob("_temp_*.parquet"))
    assert rest == [], f"Tijdelijke chunks niet opgeruimd: {rest}"


@pytest.mark.unit
def test_drop_then_recreate(db_pad: str):
    """Tweede write naar dezelfde tabel moet succesvol overschrijven."""
    from agol_naar_duckdb_v2 import _schrijf_df_naar_tabel

    df1 = pd.DataFrame({"id": range(10)})
    df2 = pd.DataFrame({"id": range(20)})

    with duckdb.connect(db_pad) as con:
        _schrijf_df_naar_tabel(con, df1, "t", db_pad)
        _schrijf_df_naar_tabel(con, df2, "t", db_pad)
        telling = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]

    assert telling == 20
