"""Anthropic tool definitions for the LESA agent.

Tools are built dynamically per session: ``run_plugin`` gets a JSON
Schema that constrains ``plugin_id`` to currently available plugins
(filtered by landscape_type) and uses ``allOf``/``if/then`` to validate
``params`` against the plugin-specific PluginParams schema.

Server-side dispatch is in ``orchestrator.py``: each tool name maps to
a handler that mutates the SessionState and returns a JSON-serialisable
result.
"""

from __future__ import annotations

from typing import Any

from lesa.plugins._registry import PluginMeta, PluginRegistry


# ── run_plugin (dynamic, registry-driven) ─────────────────────────────────

def build_run_plugin_tool(
    registry: PluginRegistry,
    available: list[PluginMeta],
) -> dict[str, Any]:
    """Build the ``run_plugin`` tool definition with discriminated params.

    The schema enforces:
    - ``plugin_id`` is one of the available plugins
    - ``params`` matches the PluginParams schema of the chosen plugin
      (via ``allOf`` with ``if/then`` discriminators).

    Server-side validation re-checks via Pydantic for safety.
    """
    plugin_ids = [m.id for m in available]

    discriminators: list[dict[str, Any]] = []
    for meta in available:
        instance = registry.get_instance(meta.id)
        params_schema = instance.params_schema()
        # Strip top-level $defs keys that may collide; keep schema flat.
        discriminators.append(
            {
                "if": {"properties": {"plugin_id": {"const": meta.id}}},
                "then": {"properties": {"params": params_schema}},
            }
        )

    return {
        "name": "run_plugin",
        "description": (
            "Voer een LESA-plugin uit op de huidige sessie. De plugin haalt "
            "data op (async) en analyseert die om claims, hypothesen en "
            "een ScopeStatement te produceren. Top-down rangorde wordt "
            "afgedwongen — een plugin op positie N draait pas als alle "
            "posities <N gedraaid of expliciet geskipt zijn. Geeft een "
            "samenvatting van de outputs terug."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plugin_id": {
                    "type": "string",
                    "enum": plugin_ids,
                    "description": "ID van de plugin (zie plugin-catalogus).",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Plugin-specifieke parameters. Schema is afhankelijk "
                        "van plugin_id (gevalideerd via if/then)."
                    ),
                },
            },
            "required": ["plugin_id", "params"],
            "allOf": discriminators,
        },
    }


# ── Meta-tools ────────────────────────────────────────────────────────────

SKIP_PLUGIN_TOOL: dict[str, Any] = {
    "name": "skip_plugin",
    "description": (
        "Sla een plugin expliciet over met motivatie. Gebruik dit als de "
        "rangorde-volgorde dat eist (bv. geomorfologie niet relevant voor "
        "stedelijk gebied) maar de hogere-orde context wel bekend is. "
        "Stilzwijgend overslaan is verboden."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plugin_id": {
                "type": "string",
                "description": "ID van de plugin die overgeslagen wordt.",
            },
            "reason": {
                "type": "string",
                "minLength": 10,
                "description": (
                    "Motivatie voor het overslaan, minimaal één zin. "
                    "Bv. 'Geomorfologie niet relevant: AOI volledig "
                    "antropogeen ontwaterd polderlandschap.'"
                ),
            },
        },
        "required": ["plugin_id", "reason"],
    },
}


PROPOSE_SYSTEEMGRENS_TOOL: dict[str, Any] = {
    "name": "propose_systeemgrens",
    "description": (
        "Stel een ecohydrologische systeemgrens voor. De expert "
        "valideert/bewerkt deze. Methoden: 'ahn_watershed' (afgeleid uit "
        "AHN watershed-analyse), 'nhi_model' (uit NHI-deelstroomgebieden), "
        "'expert_drawn' (handmatig getekend), 'aoi_copy' (gelijk aan AOI "
        "— alleen als systeemgrens samenvalt met opdrachtgrens)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["ahn_watershed", "nhi_model", "expert_drawn", "aoi_copy"],
            },
            "notes": {
                "type": "string",
                "description": "Toelichting waarom deze methode/grens is gekozen.",
            },
        },
        "required": ["method", "notes"],
    },
}


PROPOSE_HYPOTHESIS_TOOL: dict[str, Any] = {
    "name": "propose_hypothesis",
    "description": (
        "Voeg een gestructureerde hypothese toe aan de sessie. Een "
        "hypothese is een toetsbare uitspraak met expliciete falsifier "
        "en zwakste schakel. Zonder falsifier moet confidence_level "
        "'speculatief' zijn én reason_no_falsifier ingevuld."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "proposed_mechanism": {
                "type": "string",
                "description": "Welk proces wordt verondersteld (oorzaak-gevolg).",
            },
            "predicted_observation": {
                "type": "string",
                "description": "Wat zou in het veld zichtbaar moeten zijn als de hypothese klopt.",
            },
            "falsifier": {
                "type": "string",
                "description": (
                    "Wat zou de hypothese ontkrachten. Verplicht tenzij "
                    "confidence_level='speculatief'."
                ),
            },
            "reason_no_falsifier": {
                "type": "string",
                "description": "Verplicht als falsifier ontbreekt en confidence_level='speculatief'.",
            },
            "confidence_level": {
                "type": "string",
                "enum": ["sterk_onderbouwd", "plausibel", "speculatief"],
            },
            "weakest_link": {
                "type": "string",
                "description": "Zwakste schakel in de onderbouwende bewijsketen.",
            },
            "supporting_claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lijst van Claim-IDs die deze hypothese ondersteunen.",
                "default": [],
            },
            "plugin_id": {
                "type": "string",
                "description": (
                    "Plugin die deze hypothese voorstelt. Gebruik 'agent' "
                    "voor synthese-hypothesen die meerdere plugins overspannen."
                ),
                "default": "agent",
            },
        },
        "required": [
            "proposed_mechanism",
            "predicted_observation",
            "confidence_level",
            "weakest_link",
        ],
    },
}


REQUEST_EXPERT_INPUT_TOOL: dict[str, Any] = {
    "name": "request_expert_input",
    "description": (
        "Escaleer een vraag naar de expert. Gebruik dit voor "
        "methodologische keuzes (modelvalidatie, weging concurrerende "
        "hypothesen, classificatie-keuzes) of bij onzekerheid die niet "
        "uit data oplosbaar is. Wacht op antwoord voor je verder gaat."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Concrete vraag aan de expert (één zin).",
            },
            "context": {
                "type": "string",
                "description": "Wat heb je tot nu toe gedaan en waarom is deze keuze nodig.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optioneel: voorgestelde keuzes voor de expert.",
                "default": [],
            },
        },
        "required": ["question", "context"],
    },
}


GET_SESSION_STATE_TOOL: dict[str, Any] = {
    "name": "get_session_state",
    "description": (
        "Geef een samenvatting van de huidige sessie-state: AOI, "
        "voltooide en geskipte plugins, claims, hypothesen, scope. "
        "Gebruik dit om te beslissen wat de volgende stap is."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}


FINALIZE_SESSION_TOOL: dict[str, Any] = {
    "name": "finalize_session",
    "description": (
        "Markeer de sessie klaar voor export en lever een korte "
        "samenvatting met aanbevelingen voor de expert. Roep dit alleen "
        "aan nadat alle relevante plugins gedraaid zijn én er minimaal "
        "één hypothese is."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "Beknopte samenvatting (max 6 regels): wat is gevonden, "
                    "wat zijn de hoofdhypothesen, wat is de zwakste schakel."
                ),
            },
            "recommended_outputs": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "veldwerkprotocol",
                        "bureau_lesa",
                        "qgis_project",
                        "markdown_report",
                        "word_report",
                        "hypothesis_export",
                    ],
                },
                "description": "Welke output-strategieën aanbevelen voor deze sessie.",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Resterende vragen die alleen veldwerk of expert kan beantwoorden.",
                "default": [],
            },
        },
        "required": ["summary", "recommended_outputs"],
    },
}


# ── Tool catalog builder ──────────────────────────────────────────────────

def build_tool_catalog(
    registry: PluginRegistry,
    available_plugins: list[PluginMeta],
) -> list[dict[str, Any]]:
    """Build the full tool list for an Anthropic ``messages.create`` call."""
    tools: list[dict[str, Any]] = [
        GET_SESSION_STATE_TOOL,
        SKIP_PLUGIN_TOOL,
        PROPOSE_SYSTEEMGRENS_TOOL,
        PROPOSE_HYPOTHESIS_TOOL,
        REQUEST_EXPERT_INPUT_TOOL,
        FINALIZE_SESSION_TOOL,
    ]
    if available_plugins:
        tools.insert(1, build_run_plugin_tool(registry, available_plugins))
    return tools


__all__ = [
    "build_tool_catalog",
    "build_run_plugin_tool",
    "SKIP_PLUGIN_TOOL",
    "PROPOSE_SYSTEEMGRENS_TOOL",
    "PROPOSE_HYPOTHESIS_TOOL",
    "REQUEST_EXPERT_INPUT_TOOL",
    "GET_SESSION_STATE_TOOL",
    "FINALIZE_SESSION_TOOL",
]
