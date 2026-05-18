"""Agent tests: prompts, tools, runner, orchestrator (with stub Anthropic).

The Anthropic client is replaced by a scripted ``StubClient`` that returns
pre-baked responses. This lets us verify the tool-use loop, dispatch
logic, persistence, and cost tracking without network or API keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from lesa.agent.runner import PluginRunner
from lesa.domain.scope import ScopeStatement
from lesa.plugins._base import PluginInputs, PluginOutputs, PluginParams, PluginRawData
from lesa.plugins._registry import PluginRegistry, reset_registry
from lesa.session.local_store import LocalSessionStore
from lesa.session.state import SessionState
from lesa_agent.agent.orchestrator import LesaAgent
from lesa_agent.agent.prompts import build_system_prompt, render_session_context
from lesa_agent.agent.tools import build_run_plugin_tool, build_tool_catalog


# ── Stub Anthropic client ─────────────────────────────────────────────────


@dataclass
class _StubBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class _StubUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _StubResponse:
    content: list[_StubBlock]
    stop_reason: str = "end_turn"
    usage: _StubUsage = field(default_factory=_StubUsage)


class _StubMessages:
    def __init__(self, responses: list[_StubResponse]) -> None:
        self._queue = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _StubResponse:
        self.calls.append(kwargs)
        if not self._queue:
            raise AssertionError("StubClient queue exhausted")
        return self._queue.pop(0)


class StubClient:
    def __init__(self, responses: list[_StubResponse]) -> None:
        self.messages = _StubMessages(responses)


# ── Inline test plugin ────────────────────────────────────────────────────

class _DummyParams(PluginParams):
    threshold: float = 0.5
    label: str = "default"


class _DummyPlugin:
    PLUGIN_ID = "geologie_dummy"
    PLUGIN_VERSION = "0.1.0"
    PARAMS_CLASS = _DummyParams

    @classmethod
    def params_schema(cls) -> dict:
        return cls.PARAMS_CLASS.params_schema()

    def validate_inputs(self, inputs: PluginInputs) -> None:
        pass

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        return PluginRawData(metadata={"threshold": inputs.params.get("threshold")})

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        from lesa.domain.claim import Claim
        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            claims=[
                Claim(
                    id="c-dummy-001",
                    plugin_id=self.PLUGIN_ID,
                    topic="geologie",
                    text="Testclaim van dummy plugin",
                    based_on=["fixtures"],
                    uncertainty="laag",
                    substantiation="hardcoded fixture",
                ),
            ],
            scope=ScopeStatement(
                scope="plugin",
                subject_id=self.PLUGIN_ID,
                based_on=["fixtures"],
                not_tested=["alles wat niet hardcoded is"],
                uncertainty_level="middel",
                consequences="Alleen dummy-data gebruikt.",
            ),
            artifacts={"main": str(Path(inputs.artifact_dir) / "dummy.gpkg")},
        )


@pytest.fixture
def dummy_registry(tmp_path: Path, monkeypatch) -> PluginRegistry:
    """Een PluginRegistry met één dummy-plugin op rangorde-positie 1."""
    plugin_dir = tmp_path / "geologie_dummy"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "from lesa.plugins._base import PluginInputs, PluginOutputs, PluginParams, PluginRawData\n"
        "from lesa.domain.scope import ScopeStatement\n"
        "from lesa.domain.claim import Claim\n"
        "\n"
        "class DummyParams(PluginParams):\n"
        "    threshold: float = 0.5\n"
        "    label: str = 'default'\n"
        "\n"
        "class DummyPlugin:\n"
        "    PLUGIN_ID = 'geologie_dummy'\n"
        "    PLUGIN_VERSION = '0.1.0'\n"
        "    PARAMS_CLASS = DummyParams\n"
        "    @classmethod\n"
        "    def params_schema(cls):\n"
        "        return cls.PARAMS_CLASS.params_schema()\n"
        "    def validate_inputs(self, inputs):\n"
        "        pass\n"
        "    async def fetch_data(self, inputs):\n"
        "        return PluginRawData()\n"
        "    def analyze(self, inputs, raw):\n"
        "        return PluginOutputs(\n"
        "            plugin_id=self.PLUGIN_ID,\n"
        "            plugin_version=self.PLUGIN_VERSION,\n"
        "            claims=[Claim(\n"
        "                id='c1', plugin_id=self.PLUGIN_ID, topic='geologie',\n"
        "                text='dummy', based_on=['fix'], uncertainty='laag',\n"
        "                substantiation='fix')],\n"
        "            scope=ScopeStatement(\n"
        "                scope='plugin', subject_id=self.PLUGIN_ID,\n"
        "                based_on=['fix'], not_tested=[],\n"
        "                uncertainty_level='middel', consequences='dummy'),\n"
        "        )\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        yaml.dump({
            "id": "geologie_dummy",
            "version": "0.1.0",
            "name": "Geologie dummy",
            "description": "Testplugin op rangorde-positie 1",
            "rangorde_position": 1,
            "landscape_types": ["all"],
            "prerequisites": [],
            "python_class": "geologie_dummy.plugin:DummyPlugin",
        }),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    reset_registry()
    registry = PluginRegistry()
    registry.load(tmp_path)
    yield registry
    reset_registry()


# ── Prompts ───────────────────────────────────────────────────────────────

class TestPrompts:
    def test_render_session_context_empty_session(self, minimal_session: SessionState):
        ctx = render_session_context(minimal_session)
        assert "Project: Test Burgh-Haamstede" in ctx
        assert "Schaalniveau: 1" in ctx
        assert "Landschapstype: duinen" in ctx

    def test_build_system_prompt_includes_rules(self, minimal_session, dummy_registry):
        plugins = dummy_registry.list_plugins(landscape_type="duinen")
        prompt = build_system_prompt(minimal_session, plugins)
        assert "Rangordemodel" in prompt
        assert "geologie_dummy" in prompt
        assert "EPSG:28992" in prompt


# ── Tool-catalog ──────────────────────────────────────────────────────────

class TestToolCatalog:
    def test_run_plugin_tool_has_enum(self, dummy_registry):
        plugins = dummy_registry.list_plugins()
        tool = build_run_plugin_tool(dummy_registry, plugins)
        assert tool["name"] == "run_plugin"
        enum = tool["input_schema"]["properties"]["plugin_id"]["enum"]
        assert enum == ["geologie_dummy"]

    def test_run_plugin_tool_has_discriminator(self, dummy_registry):
        plugins = dummy_registry.list_plugins()
        tool = build_run_plugin_tool(dummy_registry, plugins)
        assert "allOf" in tool["input_schema"]
        assert len(tool["input_schema"]["allOf"]) == 1

    def test_full_catalog_includes_meta_tools(self, dummy_registry):
        plugins = dummy_registry.list_plugins()
        tools = build_tool_catalog(dummy_registry, plugins)
        names = [t["name"] for t in tools]
        for required in (
            "get_session_state",
            "run_plugin",
            "skip_plugin",
            "propose_systeemgrens",
            "propose_hypothesis",
            "request_expert_input",
            "finalize_session",
        ):
            assert required in names

    def test_catalog_without_plugins_omits_run_plugin(self, dummy_registry):
        tools = build_tool_catalog(dummy_registry, [])
        names = [t["name"] for t in tools]
        assert "run_plugin" not in names
        assert "skip_plugin" in names


# ── PluginRunner ──────────────────────────────────────────────────────────

class TestPluginRunner:
    @pytest.mark.asyncio
    async def test_successful_run_persists_outputs(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        runner = PluginRunner(dummy_registry, store)

        result = await runner.run(minimal_session, "geologie_dummy", {"threshold": 0.7})

        assert result.ok
        assert result.outputs is not None
        assert len(minimal_session.claims) == 1
        assert len(minimal_session.scope_statements) == 1
        reloaded = store.load(minimal_session.session_id)
        assert len(reloaded.claims) == 1

    @pytest.mark.asyncio
    async def test_run_blocked_by_rangorde(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        runner = PluginRunner(dummy_registry, store)

        from lesa.plugins._registry import PluginMeta
        fake_meta = PluginMeta(
            data={
                "id": "fake_pos3",
                "version": "0.0.1",
                "name": "Fake",
                "description": "Stub",
                "rangorde_position": 3,
                "landscape_types": ["all"],
                "prerequisites": [],
                "python_class": "x:Y",
            },
            plugin_dir=tmp_path,
        )
        dummy_registry._meta["fake_pos3"] = fake_meta

        result = await runner.run(minimal_session, "fake_pos3", {})
        assert not result.ok
        assert result.skipped_reason is not None
        assert "geomorfologie" in result.skipped_reason

    @pytest.mark.asyncio
    async def test_invalid_params_caught_by_pydantic(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        runner = PluginRunner(dummy_registry, store)
        result = await runner.run(
            minimal_session, "geologie_dummy", {"threshold": {"oeps": 1}}
        )
        assert not result.ok
        assert "Ongeldige params" in result.error


# ── Orchestrator ──────────────────────────────────────────────────────────

class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_simple_text_response_ends_turn(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        responses = [
            _StubResponse(
                content=[_StubBlock(type="text", text="Begrepen, ik plan eerst geologie.")],
                stop_reason="end_turn",
            )
        ]
        agent = LesaAgent(
            session=minimal_session,
            store=store,
            registry=dummy_registry,
            client=StubClient(responses),
        )

        report = await agent.run("Maak een LESA voor Burgh-Haamstede.")
        assert report.iterations == 1
        assert report.stopped_reason == "end_turn"
        assert "geologie" in report.final_text
        assert minimal_session.cost.input_tokens == 100
        assert minimal_session.cost.output_tokens == 50

    @pytest.mark.asyncio
    async def test_run_plugin_then_finalize(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")

        responses = [
            _StubResponse(
                content=[
                    _StubBlock(type="text", text="Eerst geologie."),
                    _StubBlock(
                        type="tool_use",
                        id="t1",
                        name="run_plugin",
                        input={"plugin_id": "geologie_dummy", "params": {"threshold": 0.5}},
                    ),
                ],
                stop_reason="tool_use",
            ),
            _StubResponse(
                content=[
                    _StubBlock(
                        type="tool_use",
                        id="t2",
                        name="finalize_session",
                        input={
                            "summary": "Eén plugin gedraaid, geen verdere stappen mogelijk in deze testopstelling.",
                            "recommended_outputs": ["qgis_project"],
                            "open_questions": [],
                        },
                    ),
                ],
                stop_reason="tool_use",
            ),
        ]
        agent = LesaAgent(
            session=minimal_session,
            store=store,
            registry=dummy_registry,
            client=StubClient(responses),
        )

        report = await agent.run("Draai geologie en finaliseer.")
        assert report.finalized
        assert report.stopped_reason == "finalized"
        assert len(minimal_session.claims) == 1
        assert minimal_session.chosen_outputs == ["qgis_project"]

    @pytest.mark.asyncio
    async def test_skip_plugin_short_reason_rejected(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        responses = [
            _StubResponse(
                content=[
                    _StubBlock(
                        type="tool_use",
                        id="t1",
                        name="skip_plugin",
                        input={"plugin_id": "geologie_dummy", "reason": "kort"},
                    ),
                ],
                stop_reason="tool_use",
            ),
            _StubResponse(
                content=[_StubBlock(type="text", text="OK, dan stop ik.")],
                stop_reason="end_turn",
            ),
        ]
        agent = LesaAgent(
            session=minimal_session,
            store=store,
            registry=dummy_registry,
            client=StubClient(responses),
        )

        report = await agent.run("Sla geologie over.")
        assert len(minimal_session.skipped_plugins) == 0
        assert report.stopped_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_request_expert_input_pauses_loop(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        responses = [
            _StubResponse(
                content=[
                    _StubBlock(
                        type="tool_use",
                        id="t1",
                        name="request_expert_input",
                        input={
                            "question": "Welke modellaag voor systeemgrens?",
                            "context": "AHN of NHI?",
                        },
                    ),
                ],
                stop_reason="tool_use",
            ),
        ]
        agent = LesaAgent(
            session=minimal_session,
            store=store,
            registry=dummy_registry,
            client=StubClient(responses),
        )

        report = await agent.run("Stel systeemgrens voor.")
        assert report.stopped_reason == "expert_input_requested"
        assert len(report.expert_questions) == 1
        assert "modellaag" in report.expert_questions[0]["question"]

    @pytest.mark.asyncio
    async def test_propose_hypothesis_persists(
        self, tmp_path, minimal_session, dummy_registry
    ):
        store = LocalSessionStore(base_dir=tmp_path / "sessions")
        responses = [
            _StubResponse(
                content=[
                    _StubBlock(
                        type="tool_use",
                        id="t1",
                        name="propose_hypothesis",
                        input={
                            "proposed_mechanism": "Kweldruk vanuit duingebied",
                            "predicted_observation": "Dotterbloem in duinvallei",
                            "falsifier": "Geen kwelindicatoren in vegetatie",
                            "confidence_level": "plausibel",
                            "weakest_link": "Veronderstelde stationariteit",
                            "supporting_claims": [],
                        },
                    ),
                ],
                stop_reason="tool_use",
            ),
            _StubResponse(
                content=[_StubBlock(type="text", text="Klaar.")],
                stop_reason="end_turn",
            ),
        ]
        agent = LesaAgent(
            session=minimal_session,
            store=store,
            registry=dummy_registry,
            client=StubClient(responses),
        )
        await agent.run("Voorstel een hypothese.")
        assert len(minimal_session.hypotheses) == 1
        assert minimal_session.hypotheses[0].confidence_level == "plausibel"
