"""Console-entrypoint ``lesa-agent`` — start een interactieve LESA-sessie.

Gebruik:
    lesa-agent --aoi path/to/aoi.geojson --project "Naam" --landscape duinen

Vereisten:
    - ``ANTHROPIC_API_KEY`` als omgevingsvariabele of in een ``.env`` op de
      huidige werkmap of in ``C:\\GIS_Projecten\\.env``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_GLOBAL_ENV = Path("C:/GIS_Projecten/.env")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if _GLOBAL_ENV.exists():
        load_dotenv(_GLOBAL_ENV)
    load_dotenv(Path.cwd() / ".env")


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "FOUT: ANTHROPIC_API_KEY niet gezet.\n"
            "  1. Kopieer .env.example naar .env\n"
            "  2. Vul de sleutel in (https://console.anthropic.com/)\n"
            "  3. Draai opnieuw",
            file=sys.stderr,
        )
        sys.exit(1)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="lesa-agent",
        description="Start een interactieve LESA-sessie.",
    )
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
        default=str(Path.cwd() / "sessions"),
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


async def _run(args: argparse.Namespace) -> None:
    from lesa.domain.aoi import AOI
    from lesa.plugins._registry import get_registry, reset_registry
    from lesa.session.local_store import LocalSessionStore
    from lesa.session.state import SessionState
    from lesa_agent.agent.orchestrator import LesaAgent

    reset_registry()
    registry = get_registry()
    print(f"Registry: {len(registry)} plugin(s) geladen")
    for meta in registry.list_plugins():
        print(f"  • {meta.id} (rangorde {meta.rangorde_position})")
    print()

    aoi = AOI.from_geojson_file(args.aoi)
    print(f"AOI: {aoi.name or args.aoi} | bbox: {tuple(round(c) for c in aoi.bbox)}")

    store = LocalSessionStore(base_dir=Path(args.sessions_dir))
    session = SessionState(
        project_name=args.project,
        aoi=aoi,
        scale_level=args.scale,
        landscape_type=args.landscape,
    )
    store.save(session)
    print(f"Sessie aangemaakt: {session.session_id[:8]}")
    print(f"  Project:        {session.project_name}")
    print(f"  Schaalniveau:   {session.scale_level}")
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
    print("Tip: 'Maak een oriënterende LESA voor dit gebied.'")
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
                hint = ""
                if tc["name"] == "run_plugin":
                    hint = f" → {tc['input'].get('plugin_id')}"
                print(f"  • {tc['name']}{hint}")

        if report.expert_questions:
            print("\n⚠ Agent wacht op expert-input:")
            for q in report.expert_questions:
                print(f"  Vraag:   {q['question']}")
                print(f"  Context: {q['context']}")

        if report.finalized:
            print("\n✓ Sessie gefinaliseerd.")
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
    args = _parse_args()  # exits via argparse op --help / fouten
    _check_api_key()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
