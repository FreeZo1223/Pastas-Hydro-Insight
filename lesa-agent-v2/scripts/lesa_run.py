"""lesa_run.py — MCP-loze LESA-inventarisatie via command-line.

Gebruik (vanuit lesa-agent-v2 root of IDE terminal):

    uv run python scripts/lesa_run.py \\
        --aoi path/to/aoi.geojson \\
        --project "Duifhuis" \\
        --scale 2 \\
        --landscape zandlandschap \\
        --plugins geomorfologie_ahn bodem_bro grondwater_pastas

Geen ANTHROPIC_API_KEY nodig. Output is een inventarisatie (feitelijke
data-acquisitie + basisanalyse), geen volledige LESA met hypothesen en
falsifiers — die vereisen een LLM-sessie via MCP of de Anthropic API.

Resultaten worden opgeslagen in ``sessions/<session_id>/``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ── PROJ fix ──────────────────────────────────────────────────────────────────
# rasterio bundelt zijn eigen PROJ (versie 1.6, compatible met GDAL 3.12+).
# pyproj heeft versie 4, PostgreSQL versie 2 — beide incompatibel met rasterio's GDAL.
# Oplossing: forceer PROJ_DATA/PROJ_LIB naar rasterio's proj_data/ vóór alle imports.
def _set_proj_data() -> None:
    try:
        import rasterio
        rasterio_proj = Path(rasterio.__file__).parent / "proj_data"
        if (rasterio_proj / "proj.db").exists():
            os.environ["PROJ_DATA"] = str(rasterio_proj)
            os.environ["PROJ_LIB"] = str(rasterio_proj)
            return
    except Exception:
        pass
    try:
        import pyproj
        proj_dir = pyproj.datadir.get_data_dir()
        if proj_dir:
            os.environ.setdefault("PROJ_DATA", proj_dir)
            os.environ.setdefault("PROJ_LIB", proj_dir)
    except Exception:
        pass

_set_proj_data()
# ── Einde PROJ fix ────────────────────────────────────────────────────────────

# Voeg repo-root toe aan sys.path zodat 'lesa' importeerbaar is
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import argparse
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lesa_run")

from lesa.domain.aoi import AOI
from lesa.plugins._registry import get_registry
from lesa.session.local_store import LocalSessionStore
from lesa.session.state import SessionState, SkippedPlugin
from lesa.agent.runner import PluginRunner

VALID_PLUGINS = [
    "geomorfologie_ahn",
    "bodem_bro",
    "grondwater_pastas",
]
VALID_LANDSCAPES = [
    "zandlandschap",
    "kleilandschap",
    "veenlandschap",
    "duinlandschap",
    "rivierkleilandschap",
    "zeekleilandschap",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lesa_run.py",
        description=(
            "LESA-inventarisatie (MCP-loos) — haalt geo-data op en "
            "berekent basisanalyse voor het opgegeven studiegebied.\n\n"
            "Let op: dit script produceert een *inventarisatie* (data + "
            "statistieken), geen volledige LESA met hypothesen en falsifiers. "
            "Die vereisen een LLM-sessie via Claude Code MCP."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--aoi",
        required=True,
        metavar="PAD",
        help="Pad naar AOI-bestand (GeoJSON, GeoPackage, Shapefile). "
             "Wordt automatisch omgezet naar EPSG:28992.",
    )
    p.add_argument(
        "--project",
        default="LESA inventarisatie",
        metavar="NAAM",
        help="Projectnaam (voor sessie-bestandsnaam en rapportage).",
    )
    p.add_argument(
        "--scale",
        type=int,
        default=2,
        choices=[1, 2, 3],
        metavar="NIVEAU",
        help="Schaalniveau: 1=regionaal, 2=lokaal, 3=detailkaart (default: 2).",
    )
    p.add_argument(
        "--landscape",
        default="zandlandschap",
        choices=VALID_LANDSCAPES,
        metavar="TYPE",
        help=f"Landschapstype ({', '.join(VALID_LANDSCAPES)}). Default: zandlandschap.",
    )
    p.add_argument(
        "--plugins",
        nargs="+",
        default=VALID_PLUGINS,
        metavar="PLUGIN_ID",
        help=(
            f"Plugins om uit te voeren (default: alle). "
            f"Keuze uit: {', '.join(VALID_PLUGINS)}."
        ),
    )
    p.add_argument(
        "--skip",
        nargs="*",
        default=[],
        metavar="PLUGIN_ID",
        help="Plugins om over te slaan (met reden via --skip-reason).",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        metavar="PAD",
        help="Map voor sessie-output (default: <repo-root>/sessions/).",
    )
    p.add_argument(
        "--params",
        default=None,
        metavar="JSON",
        help=(
            "Extra plugin-parameters als JSON-string, bijv. "
            '\'{"geomorfologie_ahn": {"resolution": 0.5, "fetch_method": "auto"}}\'. '
            "Onbekende sleutels worden genegeerd."
        ),
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        default=False,
        help="Ga door met volgende plugins ook als een plugin mislukt (default: stop bij fout).",
    )
    return p


async def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Valideer AOI-pad
    aoi_path = Path(args.aoi)
    if not aoi_path.exists():
        log.error("AOI-bestand niet gevonden: %s", aoi_path)
        return 1

    # Output-map
    sessions_dir = Path(args.output_dir) if args.output_dir else ROOT / "sessions"

    # Extra params per plugin
    extra_params: dict[str, dict] = {}
    if args.params:
        try:
            extra_params = json.loads(args.params)
        except json.JSONDecodeError as e:
            log.error("Ongeldige JSON in --params: %s", e)
            return 1

    # ── AOI laden ─────────────────────────────────────────────────────────────
    log.info("AOI laden: %s", aoi_path)
    aoi = AOI.from_geojson_file(aoi_path) if aoi_path.suffix == ".geojson" else _load_aoi_generic(aoi_path)
    log.info("AOI geladen: %s", aoi.name or aoi_path.stem)

    # ── Sessie aanmaken ───────────────────────────────────────────────────────
    store = LocalSessionStore(base_dir=sessions_dir)
    session = SessionState(
        project_name=args.project,
        aoi=aoi,
        scale_level=args.scale,
        landscape_type=args.landscape,
    )
    store.save(session)
    log.info("Sessie aangemaakt: %s", session.session_id)
    log.info("Output-map: %s", sessions_dir / session.session_id)

    # ── Skip-plugins registreren ──────────────────────────────────────────────
    for pid in args.skip:
        session.skipped_plugins.append(
            SkippedPlugin(
                plugin_id=pid,
                rangorde_position=0,
                reason="Handmatig overgeslagen via --skip argument.",
            )
        )
        log.info("Plugin overgeslagen: %s", pid)

    # ── Runner initialiseren ──────────────────────────────────────────────────
    registry = get_registry()
    runner = PluginRunner(registry=registry, store=store)

    # ── Plugins uitvoeren ─────────────────────────────────────────────────────
    plugins_to_run = [p for p in args.plugins if p not in args.skip]

    print()
    print("=" * 60)
    print(f"  LESA INVENTARISATIE — {args.project}")
    print(f"  Schaalniveau: {args.scale}  |  Landschap: {args.landscape}")
    print(f"  AOI: {aoi_path.name}")
    print("=" * 60)
    print()
    print("  Let op: dit is een inventarisatie, geen volledige LESA.")
    print("  Hypothesen en falsifiers vereisen een LLM-sessie (Claude MCP).")
    print()

    exit_code = 0
    for pid in plugins_to_run:
        plugin_params = extra_params.get(pid, {})
        print(f"--- [{pid}] starten ---")
        try:
            result = await runner.run(session, pid, plugin_params)
        except Exception as exc:
            log.exception("Onverwachte fout bij plugin %s", pid)
            print(f"  FOUT (exception): {exc}")
            exit_code = 1
            if not args.continue_on_error:
                break
            continue

        if result.ok:
            print(f"  OK  {pid}")
            _print_summary(result.outputs)
        else:
            reason = result.error or result.skipped_reason or "onbekende fout"
            print(f"  FOUT  {pid}: {reason}")
            exit_code = 1
            if not args.continue_on_error:
                log.error("Stoppen na fout in '%s'. Gebruik --continue-on-error om door te gaan.", pid)
                break

        print()

    # ── Samenvatting ──────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"  Resultaten: {sessions_dir / session.session_id}")
    print("=" * 60)
    return exit_code


def _load_aoi_generic(path: Path) -> "AOI":
    """Laad een AOI uit GeoPackage, Shapefile of andere geopandas-leesbare formats."""
    import geopandas as gpd
    from lesa.domain.aoi import AOI

    gdf = gpd.read_file(path)
    if gdf.crs and gdf.crs.to_epsg() != 28992:
        gdf = gdf.to_crs("EPSG:28992")
    geom = gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union
    return AOI(geometry=geom.__geo_interface__, name=path.stem)


def _print_summary(outputs) -> None:
    if not outputs:
        return
    if outputs.summary:
        for k, v in outputs.summary.items():
            print(f"    {k}: {v}")
    if outputs.artifacts:
        print(f"    Artifacts: {', '.join(outputs.artifacts.keys())}")
    if outputs.claims:
        print(f"    Claims: {len(outputs.claims)}")
    if outputs.hypotheses:
        print(f"    Hypothesen: {len(outputs.hypotheses)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
