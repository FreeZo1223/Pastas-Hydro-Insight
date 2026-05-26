"""
Snapshot & retentie — Ewaarnemingen
====================================
Maakt dagelijkse kopieën van:
  - ewaarnemingen.duckdb  → 04_snapshots/duckdb/YYYY-MM-DD/
  - PostgreSQL schema     → 04_snapshots/postgres/YYYY-MM-DD/dump.sql.gz

Retentie (grandfather-father-son):
  - Dagelijks  : 14 dagen
  - Wekelijks  : 8 weken  (zondag-snapshots blijven extra lang bewaard)
  - Maandelijks: 12 maanden (1e-van-de-maand snapshots blijven extra lang)

Gebruik (vanuit run_pipeline.bat NA AGOL-ingest, VOOR J:-sync):
    python snapshot.py
    python snapshot.py --skip-postgres   # alleen DuckDB
    python snapshot.py --dry-run         # tonen wat zou gebeuren

Geen schrijven naar J: hier — antivirus blokkeert dat. J:-sync gebeurt
later via robocopy /MIR aan einde van de pipeline.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import duckdb

# ── Config ────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent

load_dotenv(r"C:\GIS_Projecten\.env")
load_dotenv(_PROJECT_DIR / ".env")

DUCKDB_PAD = _PROJECT_DIR / "Databeheer" / "00_kern" / "ewaarnemingen.duckdb"
SNAPSHOT_ROOT = _PROJECT_DIR / "Databeheer" / "04_snapshots"

# PostgreSQL — credentials uit .env
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB = os.getenv("PG_DB", "ewaarnemingen")
PG_SCHEMA = os.getenv("PG_SCHEMA", "ewaarnemingen")
PG_USER = os.getenv("PG_PIPELINE_USER", "ew_pipeline")
PG_PASS = os.getenv("PG_PIPELINE_PASS", "")

# Standaard pg_dump-locatie op Windows (PostgreSQL 18)
PG_DUMP_KANDIDATEN = [
    Path(r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"),
    Path(r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe"),
    Path(r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"),
]

# Retentie
DAGEN_BEWAARD = 14
WEKEN_BEWAARD = 8
MAANDEN_BEWAARD = 12


# ── Retentie-logica ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Snapshot:
    pad: Path
    datum: date


def lijst_snapshots(map_pad: Path) -> list[Snapshot]:
    """Zoek alle YYYY-MM-DD submappen onder map_pad."""
    if not map_pad.exists():
        return []
    gevonden: list[Snapshot] = []
    for sub in map_pad.iterdir():
        if not sub.is_dir():
            continue
        try:
            d = datetime.strptime(sub.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        gevonden.append(Snapshot(pad=sub, datum=d))
    return sorted(gevonden, key=lambda s: s.datum, reverse=True)


def bepaal_te_behouden(snapshots: list[Snapshot], vandaag: date) -> set[Path]:
    """Pas grandfather-father-son retentie toe en retourneer paden om te BEHOUDEN."""
    behouden: set[Path] = set()

    grens_dag = vandaag - timedelta(days=DAGEN_BEWAARD)
    grens_week = vandaag - timedelta(weeks=WEKEN_BEWAARD)
    grens_maand_jaar = vandaag.year - (1 if vandaag.month <= MAANDEN_BEWAARD % 12 else 0)
    grens_maand = vandaag - timedelta(days=MAANDEN_BEWAARD * 31)

    for s in snapshots:
        if s.datum >= grens_dag:
            behouden.add(s.pad)
            continue
        if s.datum >= grens_week and s.datum.weekday() == 6:  # zondag
            behouden.add(s.pad)
            continue
        if s.datum >= grens_maand and s.datum.day == 1:
            behouden.add(s.pad)
            continue

    return behouden


def pas_retentie_toe(map_pad: Path, vandaag: date, dry_run: bool) -> tuple[int, int]:
    """Verwijder snapshots die buiten retentie vallen. Retourneert (behouden, verwijderd)."""
    snapshots = lijst_snapshots(map_pad)
    if not snapshots:
        return 0, 0
    behouden = bepaal_te_behouden(snapshots, vandaag)

    verwijderd = 0
    for s in snapshots:
        if s.pad in behouden:
            continue
        if dry_run:
            print(f"   [dry-run] zou verwijderen: {s.pad.name}")
        else:
            shutil.rmtree(s.pad, ignore_errors=True)
            print(f"   🗑️  verwijderd: {s.pad.name}")
        verwijderd += 1

    return len(behouden), verwijderd


# ── DuckDB snapshot ───────────────────────────────────────────────────────────


def snapshot_duckdb(doel_dir: Path, dry_run: bool) -> bool:
    """Maak een consistente kopie van DuckDB via een read-only verbinding + CHECKPOINT."""
    if not DUCKDB_PAD.exists():
        print(f"❌ DuckDB niet gevonden: {DUCKDB_PAD}")
        return False

    bron_grootte_mb = DUCKDB_PAD.stat().st_size / 1024 / 1024
    doel = doel_dir / DUCKDB_PAD.name

    if dry_run:
        print(f"   [dry-run] zou {bron_grootte_mb:.1f} MB kopiëren naar {doel}")
        return True

    doel_dir.mkdir(parents=True, exist_ok=True)

    # Eerst CHECKPOINT zodat eventuele resterende WAL meegenomen wordt.
    # Read-write open is veilig: pipeline is single-writer en deze snapshot
    # draait pas NA agol_naar_duckdb_v2.py.
    try:
        with duckdb.connect(str(DUCKDB_PAD)) as con:
            con.execute("CHECKPOINT")
    except Exception as e:
        print(f"   ⚠️  CHECKPOINT mislukt (mogelijk lock): {e}")
        print("   Doorgaan met file-copy maar WAL kan inconsistent zijn.")

    shutil.copy2(DUCKDB_PAD, doel)

    # Verificatie: open kopie read-only en tel waarnemingen-tabellen.
    try:
        with duckdb.connect(str(doel), read_only=True) as con:
            n = con.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name LIKE 'waarnemingen_%'"
            ).fetchone()[0]
        print(f"   ✅ DuckDB-snapshot: {bron_grootte_mb:.1f} MB, {n} waarnemingen-tabellen")
        return True
    except Exception as e:
        print(f"   ❌ Snapshot onleesbaar — verwijderd: {e}")
        doel.unlink(missing_ok=True)
        return False


# ── PostgreSQL snapshot ───────────────────────────────────────────────────────


def vind_pg_dump() -> Path | None:
    """Zoek pg_dump.exe op standaardlocaties of in PATH."""
    for kandidaat in PG_DUMP_KANDIDATEN:
        if kandidaat.exists():
            return kandidaat
    op_path = shutil.which("pg_dump")
    return Path(op_path) if op_path else None


def snapshot_postgres(doel_dir: Path, dry_run: bool) -> bool:
    """Dump het PostGIS-schema naar een gecomprimeerd SQL-bestand."""
    pg_dump = vind_pg_dump()
    if pg_dump is None:
        print(f"   ⚠️  pg_dump niet gevonden — sla PostgreSQL-snapshot over")
        return False

    if not PG_PASS:
        print("   ⚠️  PG_PIPELINE_PASS niet ingesteld — sla PostgreSQL-snapshot over")
        return False

    doel = doel_dir / f"{PG_DB}__{PG_SCHEMA}.sql.gz"

    if dry_run:
        print(f"   [dry-run] zou pg_dump uitvoeren → {doel}")
        return True

    doel_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PGPASSWORD"] = PG_PASS

    cmd = [
        str(pg_dump),
        "-h", PG_HOST,
        "-p", str(PG_PORT),
        "-U", PG_USER,
        "-d", PG_DB,
        "-n", PG_SCHEMA,
        "--no-owner",
        "--no-privileges",
        "-F", "p",
    ]

    try:
        # Stream pg_dump-output gzipped direct naar bestand — geen tussenbestand
        with gzip.open(doel, "wb", compresslevel=6) as fout:
            proc = subprocess.run(
                cmd,
                stdout=fout,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
                timeout=600,
            )
    except subprocess.CalledProcessError as e:
        print(f"   ❌ pg_dump faalde: {e.stderr.decode('utf-8', errors='replace')[:300]}")
        doel.unlink(missing_ok=True)
        return False
    except subprocess.TimeoutExpired:
        print("   ❌ pg_dump timeout na 10 min — verwijderd")
        doel.unlink(missing_ok=True)
        return False
    except Exception as e:
        print(f"   ❌ pg_dump fout: {e}")
        doel.unlink(missing_ok=True)
        return False

    grootte_mb = doel.stat().st_size / 1024 / 1024
    print(f"   ✅ Postgres-dump: {grootte_mb:.1f} MB (gzip)")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-postgres", action="store_true",
                        help="Sla PostgreSQL-dump over")
    parser.add_argument("--skip-duckdb", action="store_true",
                        help="Sla DuckDB-snapshot over")
    parser.add_argument("--dry-run", action="store_true",
                        help="Toon wat er zou gebeuren, schrijf/verwijder niets")
    args = parser.parse_args()

    vandaag = date.today()
    stempel = vandaag.strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"  SNAPSHOT  {stempel}{'  [DRY-RUN]' if args.dry_run else ''}")
    print("=" * 60)

    resultaten: dict[str, bool] = {}

    if not args.skip_duckdb:
        print("\n🦆 DuckDB")
        doel = SNAPSHOT_ROOT / "duckdb" / stempel
        resultaten["duckdb"] = snapshot_duckdb(doel, args.dry_run)
        if resultaten["duckdb"] and not args.dry_run:
            print("   Retentie:")
            beh, verw = pas_retentie_toe(SNAPSHOT_ROOT / "duckdb", vandaag, args.dry_run)
            print(f"   {beh} snapshots behouden, {verw} verwijderd")

    if not args.skip_postgres:
        print("\n🐘 PostgreSQL")
        doel = SNAPSHOT_ROOT / "postgres" / stempel
        resultaten["postgres"] = snapshot_postgres(doel, args.dry_run)
        if resultaten["postgres"] and not args.dry_run:
            print("   Retentie:")
            beh, verw = pas_retentie_toe(SNAPSHOT_ROOT / "postgres", vandaag, args.dry_run)
            print(f"   {beh} snapshots behouden, {verw} verwijderd")

    print("\n" + "=" * 60)
    geslaagd = [naam for naam, ok in resultaten.items() if ok]
    gefaald = [naam for naam, ok in resultaten.items() if not ok]
    print(f"  Geslaagd: {', '.join(geslaagd) or '-'}")
    if gefaald:
        print(f"  Gefaald : {', '.join(gefaald)}")
    print("=" * 60)

    return 0 if not gefaald else 1


if __name__ == "__main__":
    sys.exit(main())
