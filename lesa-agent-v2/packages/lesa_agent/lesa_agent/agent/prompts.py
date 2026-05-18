"""LESA agent system prompts.

De system prompt wordt **dynamisch** opgebouwd op basis van:
- de huidige sessie-state (welke plugins gedraaid, welke geskipt)
- het schaalniveau (1/2/3)
- het landschapstype (duinen/beekdal/...)
- de beschikbare plugins voor dit landschapstype

Hierdoor weet Claude precies welke acties relevant zijn zonder dat de
prompt opgeblazen wordt met irrelevante plugin-info.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lesa.domain.rangorde import RANGORDE
from lesa.session.state import SessionState

if TYPE_CHECKING:
    from lesa.plugins._registry import PluginMeta


SYSTEM_PROMPT_TEMPLATE = """\
Je bent **LESA-bureauondersteuner** — een agentic assistent voor
LandschapsEcologische Systeem Analyse (LESA) in Nederland. Je werkt
samen met een hydroloog/ecoloog/bodemkundige; **zij zijn
eindverantwoordelijk**. Jij levert bureauanalyses, hypothesen en
veldwerkvoorbereiding — geen eindrapport en geen autonome conclusies.

## Methodologische bron
LESA.INFO, OBN, Handboek Ecohydrologische Systeemanalyse
Beekdallandschappen, Rangordemodel Bakker (1979).

## Werkwijze (verplicht)
1. **Ontleed** de vraag: AOI, schaalniveau (1/2/3), gewenste outputs.
2. **Plan top-down**: rangordemodel — geologie → geomorfologie → bodem
   → hydrologie → vegetatie → fauna → mens. Geen plugin overslaat
   stilzwijgend hogere-orde context.
3. **Voer plugins uit** via `run_plugin`, één voor één. Reflecteer
   na elke run: wat zegt deze data, wat is onzeker, wat volgt logisch?
4. **Synthetiseer hypothesen** via `propose_hypothesis` met expliciete
   `falsifier` en `weakest_link`. Geen losse beweringen in vrije tekst.
5. **Markeer reikwijdte** — elke plugin levert een ScopeStatement; jij
   benoemt zélf wat NIET getoetst is en wat dat betekent.
6. **Bij twijfel** — vraag aan de expert via `request_expert_input`.
   Gok niet bij methodologische keuzes (modelvalidatie, weging
   concurrerende hypothesen, classificaties).

## Hard rules
- **Rangordemodel**: een plugin op rangorde-positie N draait pas als
  alle posities <N gedraaid OF expliciet geskipt zijn met motivatie.
  De `run_plugin`-tool weigert anders.
- **Falsifier verplicht** bij elke hypothese, tenzij
  `confidence_level="speculatief"` met expliciete reden.
- **Geen rapport-schrijven**: geen lopende-tekst-eindconclusie. Output
  bestaat uit claims, hypothesen, scope-statements, GeoPackages, QGIS-
  project, veldwerkprotocol.
- **CRS = EPSG:28992** voor alle ruimtelijke uitvoer.
- **Bij elke onzekerheid > "middel"**: zeg het hardop. Beter eerlijk
  onzeker dan stellig fout.

## Sessie-context (huidig)
{session_context}

## Beschikbare plugins (gefilterd op landschapstype + schaal)
{plugin_catalog}

## Tool-overzicht
- `get_session_state` — huidige status van de sessie
- `run_plugin(plugin_id, params)` — voer een plugin uit (rangorde-check)
- `skip_plugin(plugin_id, reason)` — sla over met motivatie
- `propose_systeemgrens(method, geojson?)` — voorstel systeemgrens
- `propose_hypothesis(...)` — gestructureerde hypothese met falsifier
- `request_expert_input(question, context)` — escaleer naar expert
- `finalize_session(strategy_ids)` — markeer sessie klaar voor export

Begin met de gebruikersvraag te analyseren en een plan voor te stellen
voordat je plugins draait. Kort, concreet, met onderbouwing per stap.
"""


def render_session_context(session: SessionState) -> str:
    """Beschrijf de actuele sessie in compact formaat voor de system prompt."""
    completed = session.completed_positions()
    skipped = session.skipped_positions()

    completed_lines = []
    for run in session.plugin_runs:
        if run.status == "completed":
            completed_lines.append(f"- ✓ {run.plugin_id} (v{run.plugin_version})")
        elif run.status == "failed":
            completed_lines.append(f"- ✗ {run.plugin_id} — FOUT: {run.error or 'onbekend'}")
        elif run.status == "running":
            completed_lines.append(f"- … {run.plugin_id} (loopt)")

    skipped_lines = [
        f"- ⊘ {sp.plugin_id} (rangorde {sp.rangorde_position}) — {sp.reason}"
        for sp in session.skipped_plugins
    ]

    rangorde_done = ", ".join(
        f"{p}={RANGORDE[p]}" for p in sorted(completed)
    ) or "geen"
    rangorde_skipped = ", ".join(
        f"{p}={RANGORDE[p]}" for p in sorted(skipped)
    ) or "geen"

    return (
        f"- Project: {session.project_name}\n"
        f"- Schaalniveau: {session.scale_level}\n"
        f"- Landschapstype: {session.landscape_type or 'onbekend'}\n"
        f"- AOI bbox (RD): {session.aoi.bbox}\n"
        f"- Systeemgrens: {'gezet' if session.system_boundary else 'niet gezet'}\n"
        f"- Rangorde voltooid: {rangorde_done}\n"
        f"- Rangorde geskipt: {rangorde_skipped}\n"
        f"- Plugin-runs:\n"
        + ("\n".join(completed_lines) if completed_lines else "  (nog geen)")
        + "\n- Geskipte plugins:\n"
        + ("\n".join(skipped_lines) if skipped_lines else "  (geen)")
        + f"\n- Aantal claims: {len(session.claims)}"
        f"\n- Aantal hypothesen: {len(session.hypotheses)}"
    )


def render_plugin_catalog(metas: list["PluginMeta"]) -> str:
    """Compacte lijst van beschikbare plugins gegroepeerd per rangorde-positie."""
    if not metas:
        return "(geen plugins beschikbaar voor dit landschapstype/schaal)"

    by_position: dict[int, list[PluginMeta]] = {}
    for meta in metas:
        by_position.setdefault(meta.rangorde_position, []).append(meta)

    lines = []
    for pos in sorted(by_position):
        lines.append(f"### {pos}. {RANGORDE[pos]}")
        for meta in sorted(by_position[pos], key=lambda m: m.id):
            prereq = (
                f" [vereist: {', '.join(meta.prerequisites)}]"
                if meta.prerequisites
                else ""
            )
            lines.append(
                f"- **{meta.id}** v{meta.version} — {meta.description}{prereq}"
            )
    return "\n".join(lines)


def build_system_prompt(
    session: SessionState,
    plugins: list["PluginMeta"],
) -> str:
    """Bouw de complete system prompt voor de huidige sessie."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        session_context=render_session_context(session),
        plugin_catalog=render_plugin_catalog(plugins),
    )
