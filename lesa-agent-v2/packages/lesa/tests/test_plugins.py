"""Plugin infrastructure tests: PluginParams, Protocol, Registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lesa.domain.scope import ScopeStatement
from lesa.plugins._base import Plugin, PluginInputs, PluginOutputs, PluginParams, PluginRawData
from lesa.plugins._registry import (
    PluginRegistry,
    PluginRegistryError,
    reset_registry,
)


# ── PluginParams ──────────────────────────────────────────────────────────

class TestPluginParams:
    def test_params_schema_returns_dict(self):
        schema = PluginParams.params_schema()
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"

    def test_subclass_schema_includes_field(self):
        from pydantic import Field

        class MyParams(PluginParams):
            schaal: int = Field(50_000, ge=10_000)
            met_grondwater: bool = True

        schema = MyParams.params_schema()
        assert "schaal" in schema.get("properties", {})
        assert "met_grondwater" in schema.get("properties", {})

    def test_subclass_validation(self):
        from pydantic import Field

        class MyParams(PluginParams):
            schaal: int = Field(50_000, ge=10_000)

        with pytest.raises(Exception):
            MyParams(schaal=100)  # below ge=10_000


# ── Plugin Protocol ────────────────────────────────────────────────────────

class _MinimalPlugin:
    """Minimale implementatie die voldoet aan het Plugin Protocol."""

    PLUGIN_ID = "test_minimal"
    PLUGIN_VERSION = "0.1.0"
    PARAMS_CLASS = PluginParams

    @classmethod
    def params_schema(cls) -> dict:
        return cls.PARAMS_CLASS.params_schema()

    def validate_inputs(self, inputs: PluginInputs) -> None:
        pass

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        return PluginRawData()

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            scope=ScopeStatement(
                scope="plugin",
                subject_id=self.PLUGIN_ID,
                based_on=["test"],
                not_tested=[],
                uncertainty_level="hoog",
                consequences="Testplugin zonder echte data.",
            ),
        )


class TestPluginProtocol:
    def test_minimal_plugin_satisfies_protocol(self):
        plugin = _MinimalPlugin()
        assert isinstance(plugin, Plugin)

    async def test_fetch_data_is_async(self):
        plugin = _MinimalPlugin()
        inputs = PluginInputs(
            session_id="sess-001",
            project_name="test",
            scale_level=1,
            aoi_geojson={
                "type": "Polygon",
                "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
            },
            artifact_dir="/tmp/test",
        )
        result = await plugin.fetch_data(inputs)
        assert isinstance(result, PluginRawData)

    def test_analyze_returns_outputs_with_scope(self):
        plugin = _MinimalPlugin()
        inputs = PluginInputs(
            session_id="sess-001",
            project_name="test",
            scale_level=1,
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 0]]]},
            artifact_dir="/tmp/test",
        )
        raw = PluginRawData()
        outputs = plugin.analyze(inputs, raw)
        assert isinstance(outputs, PluginOutputs)
        assert outputs.scope is not None
        assert outputs.scope.scope == "plugin"


# ── PluginRegistry ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    """Zorg dat de singleton registry leeg is per test."""
    reset_registry()
    yield
    reset_registry()


def _write_yaml(plugin_dir: Path, data: dict) -> None:
    (plugin_dir / "plugin.yaml").write_text(yaml.dump(data), encoding="utf-8")


def _write_minimal_plugin(plugin_dir: Path, class_name: str = "DummyPlugin") -> None:
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        f"""
from lesa.plugins._base import Plugin, PluginInputs, PluginOutputs, PluginParams, PluginRawData
from lesa.domain.scope import ScopeStatement

class {class_name}:
    PLUGIN_ID = "dummy"
    PLUGIN_VERSION = "0.1.0"
    PARAMS_CLASS = PluginParams

    @classmethod
    def params_schema(cls):
        return cls.PARAMS_CLASS.params_schema()

    def validate_inputs(self, inputs):
        pass

    async def fetch_data(self, inputs):
        return PluginRawData()

    def analyze(self, inputs, raw):
        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            scope=ScopeStatement(
                scope="plugin",
                subject_id=self.PLUGIN_ID,
                based_on=["test"],
                not_tested=[],
                uncertainty_level="hoog",
                consequences="test",
            ),
        )
""",
        encoding="utf-8",
    )


class TestPluginRegistry:
    def test_empty_registry_loads_no_plugins(self, tmp_path):
        registry = PluginRegistry()
        registry.load(tmp_path)
        assert len(registry) == 0

    def test_load_valid_plugin(self, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "dummy_plugin"
        plugin_dir.mkdir()
        _write_minimal_plugin(plugin_dir)
        monkeypatch.syspath_prepend(str(tmp_path))

        _write_yaml(plugin_dir, {
            "id": "dummy_plugin",
            "version": "0.1.0",
            "name": "Dummy Plugin",
            "description": "Testplugin",
            "rangorde_position": 3,
            "landscape_types": ["all"],
            "prerequisites": [],
            "python_class": "dummy_plugin.plugin:DummyPlugin",
        })

        registry = PluginRegistry()
        registry.load(tmp_path)
        assert "dummy_plugin" in registry
        assert len(registry) == 1

    def test_missing_required_key_raises(self, tmp_path):
        plugin_dir = tmp_path / "bad_plugin"
        plugin_dir.mkdir()
        _write_yaml(plugin_dir, {
            "id": "bad_plugin",
            "version": "0.1.0",
            # "name" ontbreekt
            "description": "test",
            "rangorde_position": 1,
            "python_class": "bad_plugin.plugin:Bad",
        })

        registry = PluginRegistry()
        with pytest.raises(PluginRegistryError, match="ontbrekende"):
            registry.load(tmp_path)

    def test_invalid_rangorde_raises(self, tmp_path):
        plugin_dir = tmp_path / "bad_pos"
        plugin_dir.mkdir()
        _write_yaml(plugin_dir, {
            "id": "bad_pos",
            "version": "0.1.0",
            "name": "Bad",
            "description": "test",
            "rangorde_position": 9,  # buiten 1–7
            "python_class": "bad_pos.plugin:Bad",
        })

        registry = PluginRegistry()
        with pytest.raises(PluginRegistryError, match="rangorde_position"):
            registry.load(tmp_path)

    def test_duplicate_ids_raises(self, tmp_path, monkeypatch):
        for folder in ("plugin_a", "plugin_b"):
            d = tmp_path / folder
            d.mkdir()
            _write_minimal_plugin(d)
            monkeypatch.syspath_prepend(str(tmp_path))
            _write_yaml(d, {
                "id": "dup_id",  # zelfde id
                "version": "0.1.0",
                "name": "Dup",
                "description": "test",
                "rangorde_position": 1,
                "python_class": f"{folder}.plugin:DummyPlugin",
            })

        registry = PluginRegistry()
        with pytest.raises(PluginRegistryError, match="Duplicate"):
            registry.load(tmp_path)

    def test_unknown_prerequisite_raises(self, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "dep_plugin"
        plugin_dir.mkdir()
        _write_minimal_plugin(plugin_dir)
        monkeypatch.syspath_prepend(str(tmp_path))

        _write_yaml(plugin_dir, {
            "id": "dep_plugin",
            "version": "0.1.0",
            "name": "Dep",
            "description": "test",
            "rangorde_position": 2,
            "prerequisites": ["niet_bestaande_plugin"],
            "python_class": "dep_plugin.plugin:DummyPlugin",
        })

        registry = PluginRegistry()
        with pytest.raises(PluginRegistryError, match="prerequisite"):
            registry.load(tmp_path)

    def test_list_plugins_filter_by_landscape(self, tmp_path, monkeypatch):
        for pid, lt in [("p_duin", ["duinen"]), ("p_all", ["all"])]:
            d = tmp_path / pid
            d.mkdir()
            _write_minimal_plugin(d, class_name="DummyPlugin")
            monkeypatch.syspath_prepend(str(tmp_path))
            _write_yaml(d, {
                "id": pid,
                "version": "0.1.0",
                "name": pid,
                "description": "test",
                "rangorde_position": 1,
                "landscape_types": lt,
                "python_class": f"{pid}.plugin:DummyPlugin",
            })

        registry = PluginRegistry()
        registry.load(tmp_path)

        duinen = registry.list_plugins(landscape_type="duinen")
        assert len(duinen) == 2  # p_duin + p_all

        beekdal = registry.list_plugins(landscape_type="beekdal")
        assert len(beekdal) == 1  # alleen p_all
        assert beekdal[0].id == "p_all"
