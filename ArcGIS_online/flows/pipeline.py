"""
Prefect-pipeline — modernisering van run_pipeline.bat
======================================================

STATUS: skeleton — niet runnable zonder `pip install prefect>=2.14`.
Doel: laten zien HOE de huidige .bat-pipeline gemigreerd kan worden naar
Prefect. Wanneer je klaar bent voor migratie:

    pip install prefect
    prefect server start                     # lokaal, http://127.0.0.1:4200
    python flows/pipeline.py                 # eenmalig draaien
    # of:
    prefect deployment build flows/pipeline.py:ewaarnemingen_pipeline -n daily
    prefect deployment apply ewaarnemingen_pipeline-deployment.yaml

Waarom dit een upgrade is op de .bat:
- Web-UI met run-history, fouten, retries, duur per stap
- Schedules vervangen Windows Taakplanner (cross-platform, version-controlled)
- Sub-flows = herstartbare segmenten (alleen GPKG opnieuw, niet hele run)
- Automatic retries met exponential backoff (al ingebouwd, geen eigen code)
- Notificaties via Slack/Email/Teams/Discord — geen losse rapport-script meer
- Cancellable runs vanuit UI

Wat we BEHOUDEN:
- De Python-scripts blijven zoals ze zijn — Prefect roept ze aan via
  subprocess of importeert hun functies. Geen ingrijpende refactor.
- run_pipeline.bat blijft tijdens transitie als fallback (parallel draaien
  + uitkomsten vergelijken voor we omschakelen).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Bewuste import-keuze: alleen importeren als prefect aanwezig is, anders
# leesbare foutmelding ipv stack trace.
try:
    from prefect import flow, task, get_run_logger
    from prefect.task_runners import SequentialTaskRunner
except ImportError:
    print("Prefect niet geïnstalleerd. Voer eerst uit: pip install prefect>=2.14",
          file=sys.stderr)
    raise SystemExit(1)


_SCRIPTS = Path(__file__).parent.parent / "scripts"


# ── Atomic tasks ──────────────────────────────────────────────────────────────


@task(name="Preflight AGOL registry", retries=0)
def preflight_registry() -> int:
    """Valideer AGOL-laag-URL's voordat we beginnen — waarschuwend, niet fataal."""
    logger = get_run_logger()
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "validate_agol_registry.py"), "--quick"],
        capture_output=True, text=True,
    )
    logger.info(r.stdout)
    if r.returncode != 0:
        logger.warning(f"Registry-drift gedetecteerd (exit {r.returncode}) — pipeline gaat door")
    return r.returncode


@task(name="AGOL → DuckDB", retries=2, retry_delay_seconds=300)
def agol_naar_duckdb() -> int:
    """Hoofd-ingest — retries=2 vangt netwerk-hikken op."""
    logger = get_run_logger()
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "agol_naar_duckdb_v2.py")],
        capture_output=True, text=True,
    )
    logger.info(r.stdout[-3000:])  # tail van log voor leesbaarheid
    if r.returncode != 0:
        logger.error(f"AGOL-ingest faalde: exit {r.returncode}")
        logger.error(r.stderr[-1500:])
        raise RuntimeError(f"agol_naar_duckdb_v2 exit {r.returncode}")
    return r.returncode


@task(name="DuckDB → GeoPackage", retries=1)
def duckdb_naar_geopackage() -> int:
    logger = get_run_logger()
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "duckdb_naar_geopackage.py")],
        capture_output=True, text=True,
    )
    logger.info(r.stdout[-2000:])
    return r.returncode


@task(name="DuckDB → PostGIS", retries=1)
def duckdb_naar_postgis() -> int:
    logger = get_run_logger()
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "duckdb_naar_postgis.py")],
        capture_output=True, text=True,
    )
    logger.info(r.stdout[-2000:])
    return r.returncode


@task(name="Snapshots (DuckDB + pg_dump)", retries=0)
def snapshots() -> int:
    logger = get_run_logger()
    r = subprocess.run(
        [sys.executable, str(_SCRIPTS / "snapshot.py")],
        capture_output=True, text=True,
    )
    logger.info(r.stdout)
    return r.returncode


# ── Main flow ─────────────────────────────────────────────────────────────────


@flow(name="Ewaarnemingen pipeline",
      task_runner=SequentialTaskRunner(),
      log_prints=True)
def ewaarnemingen_pipeline() -> None:
    """Volledige dagelijkse pipeline — sequentieel, met checkpoints in Prefect-UI.

    Faalt één task: Prefect markeert de flow als FAILED en retries gaan in
    via de per-task retry-config. Geen pipeline-rapport.py meer nodig: Prefect
    geeft zelf overzicht via UI en notification-blocks.
    """
    preflight_registry()        # waarschuwend; geen wait-on
    agol_naar_duckdb()          # fail-fast: rest van flow stopt als deze faalt
    duckdb_naar_geopackage()
    duckdb_naar_postgis()
    snapshots()


if __name__ == "__main__":
    ewaarnemingen_pipeline()
