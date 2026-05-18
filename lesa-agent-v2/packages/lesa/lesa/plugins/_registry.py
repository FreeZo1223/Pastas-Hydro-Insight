"""PluginRegistry — discovery, validatie en singleton toegang.

De registry scant ``plugins/<id>/`` mappen voor ``plugin.yaml`` en laadt
de bijbehorende Python-klasse dynamisch.  Een singleton
``get_registry()`` zorgt dat de scan eenmalig plaatsvindt.

plugin.yaml-structuur (minimaal):

    id: bodem_ahn
    version: "0.1.0"
    name: "Bodem + AHN analyse"
    description: "Afleiden reliëfindicatoren uit AHN4 en BRO Bodemkaart"
    rangorde_position: 3
    landscape_types: [all]
    prerequisites: []
    python_class: "lesa.plugins.bodem_ahn.plugin:BodemAhnPlugin"
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

from lesa.domain.rangorde import RangordePosition
from lesa.plugins._base import Plugin

logger = logging.getLogger(__name__)

_REQUIRED_YAML_KEYS = {
    "id",
    "version",
    "name",
    "description",
    "rangorde_position",
    "python_class",
}

_PLUGINS_DIR = Path(__file__).parent


class PluginRegistryError(Exception):
    pass


class PluginMeta:
    """Metadata van een geregistreerde plugin."""

    __slots__ = (
        "id",
        "version",
        "name",
        "description",
        "rangorde_position",
        "landscape_types",
        "prerequisites",
        "python_class",
        "plugin_dir",
        "raw",
    )

    def __init__(self, data: dict[str, Any], plugin_dir: Path) -> None:
        self.id: str = data["id"]
        self.version: str = str(data["version"])
        self.name: str = data["name"]
        self.description: str = data["description"]
        self.rangorde_position: RangordePosition = data["rangorde_position"]
        self.landscape_types: list[str] = data.get("landscape_types", ["all"])
        self.prerequisites: list[str] = data.get("prerequisites", [])
        self.python_class: str = data["python_class"]
        self.plugin_dir: Path = plugin_dir
        self.raw: dict[str, Any] = data

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "rangorde_position": self.rangorde_position,
            "landscape_types": self.landscape_types,
            "prerequisites": self.prerequisites,
        }


class PluginRegistry:
    """Directory-scan registry voor LESA-plugins.

    Gebruik ``get_registry()`` voor de singleton instantie.
    """

    def __init__(self) -> None:
        self._meta: dict[str, PluginMeta] = {}
        self._instances: dict[str, Plugin] = {}
        self._loaded = False

    # ── Discovery ────────────────────────────────────────────────────────

    def load(self, plugins_dir: Path = _PLUGINS_DIR) -> None:
        """Scan plugins_dir voor subdirectories met een plugin.yaml."""
        if self._loaded:
            return

        errors: list[str] = []

        for subdir in sorted(plugins_dir.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith("_"):
                continue
            yaml_path = subdir / "plugin.yaml"
            if not yaml_path.exists():
                continue

            try:
                meta = self._load_yaml(yaml_path, subdir)
            except PluginRegistryError as exc:
                errors.append(str(exc))
                continue

            if meta.id in self._meta:
                errors.append(
                    f"Duplicate plugin id '{meta.id}': "
                    f"{self._meta[meta.id].plugin_dir} en {subdir}"
                )
                continue

            self._meta[meta.id] = meta
            logger.debug("Plugin geladen: %s v%s (rangorde %d)", meta.id, meta.version, meta.rangorde_position)

        if errors:
            raise PluginRegistryError(
                f"{len(errors)} fout(en) bij plugin-laden:\n" + "\n".join(f"  • {e}" for e in errors)
            )

        self._validate_graph()
        self._loaded = True
        logger.info("PluginRegistry: %d plugin(s) geladen", len(self._meta))

    def _load_yaml(self, yaml_path: Path, plugin_dir: Path) -> PluginMeta:
        with yaml_path.open(encoding="utf-8") as fh:
            try:
                data = yaml.safe_load(fh)
            except yaml.YAMLError as exc:
                raise PluginRegistryError(f"YAML-parsefout in {yaml_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise PluginRegistryError(f"{yaml_path}: geen geldige YAML-mapping")

        missing = _REQUIRED_YAML_KEYS - data.keys()
        if missing:
            raise PluginRegistryError(
                f"{yaml_path}: ontbrekende verplichte sleutels: {sorted(missing)}"
            )

        pos = data["rangorde_position"]
        if pos not in range(1, 8):
            raise PluginRegistryError(
                f"{yaml_path}: rangorde_position moet 1–7 zijn, niet {pos!r}"
            )

        return PluginMeta(data, plugin_dir)

    def _validate_graph(self) -> None:
        """Controleer dat prerequisites bestaan en geen cycles bevatten."""
        errors: list[str] = []

        for meta in self._meta.values():
            for prereq in meta.prerequisites:
                if prereq not in self._meta:
                    errors.append(
                        f"Plugin '{meta.id}' verwijst naar onbekende prerequisite '{prereq}'"
                    )

        if errors:
            raise PluginRegistryError(
                "Prerequisite-fouten:\n" + "\n".join(f"  • {e}" for e in errors)
            )

        # Cycle-detectie via DFS
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(plugin_id: str) -> None:
            if plugin_id in stack:
                raise PluginRegistryError(
                    f"Cycle gedetecteerd in prerequisites bij plugin '{plugin_id}'"
                )
            if plugin_id in visited:
                return
            stack.add(plugin_id)
            for prereq in self._meta[plugin_id].prerequisites:
                dfs(prereq)
            stack.discard(plugin_id)
            visited.add(plugin_id)

        for pid in self._meta:
            dfs(pid)

    # ── Toegang ──────────────────────────────────────────────────────────

    def get_meta(self, plugin_id: str) -> PluginMeta | None:
        return self._meta.get(plugin_id)

    def list_plugins(
        self,
        landscape_type: str | None = None,
        rangorde_position: RangordePosition | None = None,
    ) -> list[PluginMeta]:
        """Geef gefilterde lijst van beschikbare plugins."""
        result = list(self._meta.values())

        if landscape_type is not None:
            result = [
                m for m in result
                if "all" in m.landscape_types or landscape_type in m.landscape_types
            ]

        if rangorde_position is not None:
            result = [m for m in result if m.rangorde_position == rangorde_position]

        return sorted(result, key=lambda m: (m.rangorde_position, m.id))

    def get_instance(self, plugin_id: str) -> Plugin:
        """Geef een gecachede instantie van de plugin-klasse."""
        if plugin_id not in self._instances:
            meta = self._meta.get(plugin_id)
            if meta is None:
                raise KeyError(f"Plugin '{plugin_id}' niet gevonden in registry")
            self._instances[plugin_id] = self._instantiate(meta)
        return self._instances[plugin_id]

    def _instantiate(self, meta: PluginMeta) -> Plugin:
        module_path, class_name = meta.python_class.rsplit(":", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise PluginRegistryError(
                f"Kan module '{module_path}' voor plugin '{meta.id}' niet importeren: {exc}"
            ) from exc

        cls = getattr(module, class_name, None)
        if cls is None:
            raise PluginRegistryError(
                f"Klasse '{class_name}' niet gevonden in module '{module_path}'"
            )

        if not isinstance(cls, type):
            raise PluginRegistryError(
                f"'{class_name}' in '{module_path}' is geen klasse"
            )

        instance = cls()
        if not isinstance(instance, Plugin):
            raise PluginRegistryError(
                f"'{meta.python_class}' voldoet niet aan het Plugin Protocol"
            )

        return instance

    def __len__(self) -> int:
        return len(self._meta)

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._meta


# ── Singleton ─────────────────────────────────────────────────────────────

_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    """Geef de singleton PluginRegistry instantie (laadt eenmalig)."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
        _registry.load()
    return _registry


def reset_registry() -> None:
    """Reset de singleton — voor gebruik in tests."""
    global _registry
    _registry = None
