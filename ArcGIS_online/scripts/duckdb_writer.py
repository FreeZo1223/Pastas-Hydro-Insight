"""
DuckDB Writer — geïsoleerd subprocess voor DuckDB-writes
=========================================================

Draait als APART PROCES zodat heap-corruption (STATUS_HEAP_CORRUPTION,
exit -1073740940) in de DuckDB C-extension de fetch-stap niet mee neemt.

Aanroep vanuit agol_naar_duckdb_v2.py:
    subprocess.run([sys.executable, "duckdb_writer.py",
                    "--staging", "/pad/naar/06_staging/YYYYMMDD_HHMM"])

Exit codes:
    0 = alles geschreven, geverifieerd, staging opgeruimd
    1 = schrijffout of verificatiefout (staging bewaard voor diagnose)
    2 = staging-dir niet gevonden of manifest corrupt

Staging-directorystructuur:
    06_staging/YYYYMMDD_HHMM/
        manifest.json           ← verwachte soortgroepen + rij-aantallen
        waarnemingen_vogels.parquet
        waarnemingen_vleermuizen.parquet
        ...
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))

from agol_naar_duckdb_v2 import (
    CHUNKED_WRITE_THRESHOLD,
    CHUNK_RIJEN,
    DUCKDB_PAD,
    _schrijf_df_naar_tabel,
    maak_df_duckdb_veilig,
)

STAGING_ROOT = Path(DUCKDB_PAD).parent.parent / "06_staging"
MANIFEST_NAAM = "manifest.json"


# ── Manifest ──────────────────────────────────────────────────────────────────


def laad_manifest(staging_dir: Path) -> dict:
    pad = staging_dir / MANIFEST_NAAM
    if not pad.exists():
        raise FileNotFoundError(f"Manifest niet gevonden: {pad}")
    return json.loads(pad.read_text(encoding="utf-8"))


# ── Write ─────────────────────────────────────────────────────────────────────


def schrijf_staging_naar_duckdb(staging_dir: Path, db_pad: str) -> bool:
    """Lees alle parquets uit staging_dir en schrijf naar DuckDB.

    Retourneert True bij volledig succes, False bij enige fout.
    Ruimt staging op bij succes. Laat staging staan bij fout.
    """
    manifest = laad_manifest(staging_dir)
    entries = manifest.get("tabellen", {})

    if not entries:
        print("⚠️  Manifest heeft geen tabellen — niets te doen.")
        return False

    print(f"\n{'='*60}")
    print(f"  🦆 DUCKDB WRITER — {db_pad}")
    print(f"  📦 Staging: {staging_dir.name}")
    print(f"  📋 {len(entries)} tabellen")
    print(f"{'='*60}\n")

    fouten: list[str] = []
    totaal = 0

    with duckdb.connect(db_pad) as con:

        con.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_log (
                run_timestamp TIMESTAMP,
                soortgroep    TEXT,
                rijen         INTEGER,
                datum_pct     DOUBLE,
                bron_types    TEXT
            )
        """)

        for tabel, info in entries.items():
            parquet_pad = staging_dir / info["bestand"]
            verwacht = info["verwacht_rijen"]

            print(f"  📊 {tabel} ({verwacht:,} rijen verwacht)...", end=" ", flush=True)

            if not parquet_pad.exists():
                boodschap = f"parquet niet gevonden: {parquet_pad.name}"
                print(f"❌ {boodschap}")
                fouten.append(f"{tabel}: {boodschap}")
                continue

            try:
                df = pd.read_parquet(parquet_pad)
                df_veilig = maak_df_duckdb_veilig(df)
                del df

                _schrijf_df_naar_tabel(con, df_veilig, tabel, db_pad)

                telling = con.execute(
                    f"SELECT COUNT(*) FROM {tabel}"
                ).fetchone()[0]

                if telling != verwacht:
                    boodschap = (
                        f"telling-mismatch: {telling:,} geschreven "
                        f"maar {verwacht:,} verwacht"
                    )
                    print(f"❌ {boodschap}")
                    fouten.append(f"{tabel}: {boodschap}")
                    continue

                datum_pct = round(
                    (df_veilig.get("datum_bron", pd.Series()) != "onbekend").mean() * 100, 1
                )
                bron_types = (
                    ", ".join(df_veilig["_bron_type"].unique())
                    if "_bron_type" in df_veilig.columns else "?"
                )
                con.execute(
                    "INSERT INTO _pipeline_log VALUES (?,?,?,?,?)",
                    [datetime.now(), tabel, telling, datum_pct, bron_types],
                )

                totaal += telling
                print(f"✅ ({telling:,} rijen)")

            except Exception as exc:
                print(f"❌ {exc}")
                fouten.append(f"{tabel}: {exc}")

        if fouten:
            print(f"\n❌ {len(fouten)} fouten — DuckDB-write NIET gecommit.")
            for f in fouten:
                print(f"   • {f}")
            return False

        con.execute("""
            CREATE OR REPLACE VIEW overzicht AS
            SELECT soortgroep, rijen, datum_pct, bron_types, run_timestamp
            FROM _pipeline_log ORDER BY rijen DESC
        """)

        print("\n  💾 Commit + CHECKPOINT...", end=" ", flush=True)
        con.commit()
        con.execute("CHECKPOINT")
        print("✅")

    # Post-write verificatie in verse read-only verbinding
    print("\n  🔍 Post-write verificatie...", end=" ", flush=True)
    with duckdb.connect(db_pad, read_only=True) as verify:
        tabs_in_db = {
            r[0] for r in verify.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'waarnemingen_%'"
            ).fetchall()
        }
    verwachte_tabs = set(entries.keys())
    ontbrekend = verwachte_tabs - tabs_in_db
    if ontbrekend:
        print(f"❌ Ontbrekend na verificatie: {ontbrekend}")
        return False
    print(f"✅ {len(verwachte_tabs)} tabellen aanwezig")

    print(f"\n  ✅ Totaal {totaal:,} rijen geschreven en geverifieerd")
    return True


# ── Staging cleanup ───────────────────────────────────────────────────────────


def ruim_staging_op(staging_dir: Path) -> None:
    """Verwijder staging-dir na succesvolle write."""
    import shutil
    try:
        shutil.rmtree(staging_dir)
        print(f"  🗑️  Staging opgeruimd: {staging_dir.name}")
    except Exception as exc:
        print(f"  ⚠️  Staging opruimen mislukt (niet kritiek): {exc}")


def ruim_oude_stagings_op(max_leeftijd_uren: int = 48) -> None:
    """Verwijder staging-dirs ouder dan max_leeftijd_uren."""
    if not STAGING_ROOT.exists():
        return
    grens = datetime.now() - timedelta(hours=max_leeftijd_uren)
    for sub in STAGING_ROOT.iterdir():
        if not sub.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(sub.stat().st_mtime)
            if mtime < grens:
                import shutil
                shutil.rmtree(sub)
                print(f"  🗑️  Oude staging verwijderd: {sub.name}")
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staging", required=True,
        help="Pad naar staging-directory (06_staging/YYYYMMDD_HHMM)",
    )
    parser.add_argument(
        "--bewaar-staging", action="store_true",
        help="Ruim staging NIET op na succes (debug-modus)",
    )
    args = parser.parse_args()

    staging_dir = Path(args.staging)
    if not staging_dir.exists():
        print(f"❌ Staging-dir niet gevonden: {staging_dir}")
        return 2

    print(f"🚀 DuckDB Writer gestart: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Staging : {staging_dir}")
    print(f"   DuckDB  : {DUCKDB_PAD}")

    geslaagd = schrijf_staging_naar_duckdb(staging_dir, DUCKDB_PAD)

    if geslaagd and not args.bewaar_staging:
        ruim_staging_op(staging_dir)
    elif not geslaagd:
        print(f"\n⚠️  Staging bewaard voor diagnose: {staging_dir}")

    return 0 if geslaagd else 1


if __name__ == "__main__":
    sys.exit(main())
