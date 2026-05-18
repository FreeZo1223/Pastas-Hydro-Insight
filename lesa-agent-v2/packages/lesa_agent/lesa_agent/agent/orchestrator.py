"""LESA agent orchestrator — Anthropic tool-use loop.

The orchestrator drives the LESA pipeline by giving Claude a session-
specific tool catalog and looping until either:
- Claude returns ``stop_reason="end_turn"`` (assistant has nothing more
  to do without further input);
- ``finalize_session`` is called (assistant signals completion);
- ``max_iters`` is reached (safety cap);
- the cumulative cost exceeds ``cost_cap_eur`` (budget cap).

Each tool call is dispatched server-side: ``run_plugin`` defers to
``PluginRunner``; meta-tools mutate ``SessionState`` directly. After
every iteration the session is saved so a crash never loses progress.

The Anthropic client is injected (default: ``anthropic.Anthropic``) so
tests can supply a stub. We don't rely on prompt-string parsing —
all decisions flow through ``tool_use`` and ``tool_result`` blocks.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from lesa_agent.agent.prompts import build_system_prompt
from lesa_agent.agent.tools import build_tool_catalog
from lesa.agent.runner import PluginRunResult, PluginRunner
from lesa.domain.aoi import SystemBoundary
from lesa.domain.hypothesis import Hypothesis
from lesa.plugins._registry import PluginRegistry
from lesa.session.local_store import LocalSessionStore
from lesa.session.state import AgentTurn, SessionState, SkippedPlugin

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_ITERS = 30
DEFAULT_MAX_TOKENS = 4096
DEFAULT_COST_CAP_EUR = 5.0


class _AnthropicLike(Protocol):
    """Minimal protocol for Anthropic client (real or stub)."""

    @property
    def messages(self) -> Any: ...  # noqa: ANN401


class AgentRunReport:
    """Resultaat van één ``LesaAgent.run`` aanroep."""

    __slots__ = (
        "session_id",
        "iterations",
        "stopped_reason",
        "tool_calls",
        "final_text",
        "finalized",
        "expert_questions",
    )

    def __init__(
        self,
        session_id: str,
        iterations: int,
        stopped_reason: str,
        tool_calls: list[dict[str, Any]],
        final_text: str,
        finalized: bool,
        expert_questions: list[dict[str, Any]],
    ) -> None:
        self.session_id = session_id
        self.iterations = iterations
        self.stopped_reason = stopped_reason
        self.tool_calls = tool_calls
        self.final_text = final_text
        self.finalized = finalized
        self.expert_questions = expert_questions


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class LesaAgent:
    """Tool-use loop voor één LESA-sessie.

    Eén instantie per sessie; meerdere ``run()``-calls zijn toegestaan
    en bouwen voort op de geaccumuleerde ``agent_history`` in de state.
    """

    def __init__(
        self,
        session: SessionState,
        store: LocalSessionStore,
        registry: PluginRegistry,
        client: _AnthropicLike | None = None,
        model: str = DEFAULT_MODEL,
        max_iters: int = DEFAULT_MAX_ITERS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        cost_cap_eur: float = DEFAULT_COST_CAP_EUR,
    ) -> None:
        self.session = session
        self.store = store
        self.registry = registry
        self.runner = PluginRunner(registry, store)
        self.client = client if client is not None else _make_default_client()
        self.model = model
        self.max_iters = max_iters
        self.max_tokens = max_tokens
        self.cost_cap_eur = cost_cap_eur

    # ── Public API ──────────────────────────────────────────────────────

    async def run(self, user_message: str) -> AgentRunReport:
        """Voer één agent-turn uit op basis van een user-bericht.

        Mutatie van ``self.session`` is in-place; na elke iteratie wordt
        de state naar disk gepersisteerd.
        """
        # Persist user turn first
        self.session.agent_history.append(
            AgentTurn(role="user", content=user_message, timestamp=_utcnow())
        )
        self.store.save(self.session)

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message}
        ]
        tool_calls: list[dict[str, Any]] = []
        expert_questions: list[dict[str, Any]] = []
        finalized = False
        stopped_reason = "max_iters"
        final_text = ""

        for iteration in range(1, self.max_iters + 1):
            # Cost cap (gemeten ná vorige stap)
            if self.session.cost.estimated_eur >= self.cost_cap_eur:
                stopped_reason = "cost_cap"
                logger.warning(
                    "Cost cap %.2f bereikt na iteratie %d", self.cost_cap_eur, iteration - 1
                )
                break

            # Build system prompt + tools per iteratie zodat sessie-state
            # altijd actueel is (rangorde-status verandert tijdens loop).
            available = self.registry.list_plugins(
                landscape_type=self.session.landscape_type
            )
            system_prompt = build_system_prompt(self.session, available)
            tools = build_tool_catalog(self.registry, available)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

            self._track_usage(response)

            assistant_blocks = _content_to_dicts(response.content)
            messages.append({"role": "assistant", "content": assistant_blocks})

            # Persist assistant turn (text + tool_use beschrijvingen)
            text_chunks = [b["text"] for b in assistant_blocks if b.get("type") == "text"]
            self.session.agent_history.append(
                AgentTurn(
                    role="assistant",
                    content="\n".join(text_chunks),
                    tool_calls=[
                        {"name": b["name"], "input": b["input"]}
                        for b in assistant_blocks
                        if b.get("type") == "tool_use"
                    ],
                    timestamp=_utcnow(),
                )
            )

            stop_reason = getattr(response, "stop_reason", None)

            if stop_reason != "tool_use":
                final_text = "\n".join(text_chunks)
                stopped_reason = stop_reason or "end_turn"
                self.store.save(self.session)
                break

            # Dispatch alle tool_use blokken in deze response
            tool_results: list[dict[str, Any]] = []
            for block in assistant_blocks:
                if block.get("type") != "tool_use":
                    continue

                tool_name = block["name"]
                tool_input = block.get("input", {}) or {}
                tool_use_id = block["id"]

                logger.info("Tool call: %s", tool_name)
                tool_calls.append({"name": tool_name, "input": tool_input})

                try:
                    result = await self._dispatch_tool(tool_name, tool_input)
                    is_error = False
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Tool '%s' faalde", tool_name)
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                    is_error = True

                if tool_name == "finalize_session" and not is_error:
                    finalized = True
                if tool_name == "request_expert_input" and not is_error:
                    expert_questions.append(tool_input)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": _to_text(result),
                        "is_error": is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            self.store.save(self.session)

            if finalized:
                stopped_reason = "finalized"
                break

            if expert_questions and not finalized:
                # Wacht op expert: stop loop, gebruiker beantwoordt en roept
                # ``run()`` opnieuw aan met antwoord als nieuwe user_message.
                stopped_reason = "expert_input_requested"
                break

        return AgentRunReport(
            session_id=self.session.session_id,
            iterations=iteration,
            stopped_reason=stopped_reason,
            tool_calls=tool_calls,
            final_text=final_text,
            finalized=finalized,
            expert_questions=expert_questions,
        )

    # ── Tool dispatch ───────────────────────────────────────────────────

    async def _dispatch_tool(self, name: str, args: dict[str, Any]) -> Any:  # noqa: ANN401
        if name == "get_session_state":
            return self.session.summary()

        if name == "run_plugin":
            return await self._handle_run_plugin(args)

        if name == "skip_plugin":
            return self._handle_skip_plugin(args)

        if name == "propose_systeemgrens":
            return self._handle_propose_systeemgrens(args)

        if name == "propose_hypothesis":
            return self._handle_propose_hypothesis(args)

        if name == "request_expert_input":
            return {
                "status": "queued",
                "question": args.get("question"),
                "context": args.get("context"),
                "options": args.get("options", []),
                "note": "Wachten op expert. Sessie is gepauzeerd; antwoord komt in volgende run().",
            }

        if name == "finalize_session":
            return self._handle_finalize(args)

        return {"error": f"Onbekende tool: {name}"}

    async def _handle_run_plugin(self, args: dict[str, Any]) -> dict[str, Any]:
        plugin_id = args.get("plugin_id")
        params = args.get("params", {}) or {}
        if not isinstance(plugin_id, str):
            return {"error": "plugin_id ontbreekt of is geen string"}
        result: PluginRunResult = await self.runner.run(self.session, plugin_id, params)
        return result.as_summary()

    def _handle_skip_plugin(self, args: dict[str, Any]) -> dict[str, Any]:
        plugin_id = args.get("plugin_id")
        reason = args.get("reason", "")
        meta = self.registry.get_meta(plugin_id) if plugin_id else None
        if meta is None:
            return {"error": f"Plugin '{plugin_id}' niet gevonden"}
        if not reason or len(reason) < 10:
            return {"error": "reason moet minimaal 10 tekens zijn"}

        skipped = SkippedPlugin(
            plugin_id=plugin_id,
            rangorde_position=meta.rangorde_position,
            reason=reason,
        )
        self.session.skipped_plugins.append(skipped)
        self.session.updated_at = _utcnow()
        self.store.save(self.session)
        return {
            "status": "skipped",
            "plugin_id": plugin_id,
            "rangorde_position": meta.rangorde_position,
        }

    def _handle_propose_systeemgrens(self, args: dict[str, Any]) -> dict[str, Any]:
        method = args.get("method")
        notes = args.get("notes", "")
        if method == "aoi_copy":
            geometry = self.session.aoi.geometry
        else:
            return {
                "status": "pending_expert",
                "note": (
                    f"Methode '{method}' vereist aanvullende data of expert-actie. "
                    f"Voor een echte run hoort hier een geometry-output van de "
                    f"systeemgrens_voorstel-plugin. Voor nu: roep run_plugin aan."
                ),
            }

        self.session.system_boundary = SystemBoundary(
            geometry=geometry,
            derivation_method=method,
            expert_accepted=False,
            notes=notes,
        )
        self.session.updated_at = _utcnow()
        self.store.save(self.session)
        return {
            "status": "proposed",
            "method": method,
            "expert_accepted": False,
            "note": "Expert moet nog accepteren via expert_accepted=True.",
        }

    def _handle_propose_hypothesis(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            hyp = Hypothesis(
                id=_new_id(),
                plugin_id=args.get("plugin_id", "agent"),
                proposed_mechanism=args["proposed_mechanism"],
                predicted_observation=args["predicted_observation"],
                falsifier=args.get("falsifier"),
                reason_no_falsifier=args.get("reason_no_falsifier"),
                confidence_level=args["confidence_level"],
                weakest_link=args["weakest_link"],
                supporting_claims=args.get("supporting_claims", []),
            )
        except (KeyError, ValueError) as exc:
            return {"error": f"Ongeldige hypothese: {exc}"}

        self.session.hypotheses.append(hyp)
        self.session.updated_at = _utcnow()
        self.store.save(self.session)
        return {
            "status": "added",
            "id": hyp.id,
            "confidence_level": hyp.confidence_level,
            "total_hypotheses": len(self.session.hypotheses),
        }

    def _handle_finalize(self, args: dict[str, Any]) -> dict[str, Any]:
        self.session.chosen_outputs = args.get("recommended_outputs", [])
        self.session.updated_at = _utcnow()
        self.store.save(self.session)
        return {
            "status": "finalized",
            "summary": args.get("summary", ""),
            "recommended_outputs": self.session.chosen_outputs,
            "open_questions": args.get("open_questions", []),
            "session_summary": self.session.summary(),
        }

    # ── Cost tracking ───────────────────────────────────────────────────

    def _track_usage(self, response: Any) -> None:  # noqa: ANN401
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        self.session.cost = self.session.cost.add(input_tokens, output_tokens)


# ── Helpers ───────────────────────────────────────────────────────────────

def _content_to_dicts(content: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    """Normaliseer Anthropic content blocks naar JSON-friendly dicts."""
    blocks: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, dict):
            blocks.append(item)
            continue

        item_type = getattr(item, "type", None)
        if item_type == "text":
            blocks.append({"type": "text", "text": getattr(item, "text", "")})
        elif item_type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": getattr(item, "id", ""),
                    "name": getattr(item, "name", ""),
                    "input": getattr(item, "input", {}),
                }
            )
        else:
            # Fallback: best-effort dict
            blocks.append(
                {k: getattr(item, k) for k in dir(item) if not k.startswith("_")}
            )
    return blocks


def _to_text(value: Any) -> str:  # noqa: ANN401
    """Serialise tool result to JSON string for tool_result content."""
    import json
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _make_default_client() -> _AnthropicLike:
    """Lazy-import anthropic.Anthropic so tests can run without the dep."""
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "anthropic SDK niet geïnstalleerd. Voeg toe aan dependencies."
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY niet gezet. Zet in .env of injecteer een client expliciet."
        )
    return Anthropic(api_key=api_key)
