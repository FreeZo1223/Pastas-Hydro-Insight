"""Minimale REPL om een LESA-sessie te starten en de agent te bevragen.

Gebruik:
    uv run python scripts/run_session.py \\
        --aoi examples/burgh_haamstede/aoi.geojson \\
        --project "Burgh-Haamstede test" \\
        --scale 2 \\
        --landscape duinen

Vervolgens voer je berichten in (of 'quit' om te stoppen).

Vereisten:
    ANTHROPIC_API_KEY in .env of omgevingsvariabele.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(r"C:\GIS_Projecten\.env")
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "FOUT: ANTHROPIC_API_KEY niet gezet.\n"
            "  1. Kopieer .env.example naar .env\n"
            "  2. Vul de sleutel in\n"
            "  3. Draai opnieuw",
            file=sys.stderr,
        )
        sys.exit(1)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aoi", required=True, help="Pad naar GeoJSON-bestand (EPSG:28992)")
    p.add_argument("--project", default="LESA sessie", help="Projectnaam")
    p.add_argument("--scale", type=int, choices=[1, 2, 3], default=2, help="Schaalniveau")
    p.add_argument(
        "--landscape",
        choices=["duinen", "beekdal", "veen", "zandlandschap", "klei"],
        default=None,
        help="Landschapstype (optioneel)",
    )
    p.add_argument(
        "--sessions-dir",
        default=str(ROOT / "sessions"),
        help="Basis-map voor sessie-opslag",
    )
    p.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude-model (default: claude-sonnet-4-6)",
    )
    p.add_argument(
        "--max-cost",
        type=float,
        default=5.0,
        help="Maximale kosten in EUR per run (default: 5.0)",
    )
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    from lesa_agent.agent.orchestrator import LesaAgent
    from lesa.domain.aoi import AOI
    from lesa.plugins._registry import get_registry, reset_registry
    from lesa.session.local_store import LocalSessionStore
    from lesa.session.state import SessionState

    # Registry laden vanuit plugins-dir
    reset_registry()
    registry = get_registry()
    n_plugins = len(registry)
    print(f"Registry: {n_plugins} plugin(s) geladen")
    for meta in registry.list_plugins():
        print(f"  • {meta.id} (rangorde {meta.rangorde_position})")
    print()

    # AOI laden
    aoi = AOI.from_geojson_file(args.aoi)
    print(f"AOI: {aoi.name or args.aoi} | bbox: {tuple(round(c) for c in aoi.bbox)}")

    # Sessie aanmaken
    store = LocalSessionStore(base_dir=Path(args.sessions_dir))
    session = SessionState(
        project_name=args.project,
        aoi=aoi,
        scale_level=args.scale,
        landscape_type=args.landscape,
    )
    store.save(session)
    print(f"Sessie aangemaakt: {session.session_id[:8]}")
    print(f"  Project:      {session.project_name}")
    print(f"  Schaalniveau: {session.scale_level}")
    print(f"  Landschapstype: {session.landscape_type or '(niet opgegeven)'}")
    print()

    agent = LesaAgent(
        session=session,
        store=store,
        registry=registry,
        model=args.model,
        cost_cap_eur=args.max_cost,
    )

    print("LESA-agent klaar. Typ je vraag (of 'quit' om te stoppen).")
    print("Tip: begin met 'Maak een oriënterende LESA voor dit gebied.' of")
    print("     'Sla rangorde 1 (geologie) over en draai geomorfologie.'")
    print()

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSessie beëindigd.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Sessie beëindigd.")
            break
        if not user_input:
            continue

        print()
        report = await agent.run(user_input)

        if report.final_text:
            print("Agent:\n" + report.final_text)
        elif not report.tool_calls:
            print("(Geen tekstuele respons)")

        if report.tool_calls:
            print(f"\n[{len(report.tool_calls)} tool-call(s) in {report.iterations} iteratie(s)]")
            for tc in report.tool_calls:
                result_hint = ""
                if tc["name"] == "run_plugin":
                    result_hint = f" → {tc['input'].get('plugin_id')}"
                print(f"  • {tc['name']}{result_hint}")

        if report.expert_questions:
            print("\n⚠ Agent wacht op expert-input:")
            for q in report.expert_questions:
                print(f"  Vraag: {q['question']}")
                print(f"  Context: {q['context']}")

        if report.finalized:
            print(f"\n✓ Sessie gefinaliseerd.")
            print(f"  State: sessions/{session.session_id[:8]}/")

        cost = session.cost
        print(
            f"\n[Kosten: €{cost.estimated_eur:.4f} | "
            f"in: {cost.input_tokens:,} / out: {cost.output_tokens:,} tokens | "
            f"stop: {report.stopped_reason}]"
        )
        print()


def main() -> None:
    _load_env()
    _check_api_key()
    args = _parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
