"""Scaffold een nieuwe LESA-plugin.

Gebruik:
    uv run python scripts/new_plugin.py <plugin_id> --rangorde 3 [--landscape duinen]

Maakt:
    packages/lesa/lesa/plugins/<plugin_id>/
        __init__.py
        plugin.yaml
        plugin.py        ← Plugin-klasse-skelet
        params.py        ← PluginParams-skelet
        tests/test_plugin.py

Schrijft géén code-logica; geeft alleen de boilerplate. Daarna:
1. Open `plugin.yaml` en pas description + landschapstypen aan.
2. Open `plugin.py` en implementeer fetch_data() + analyze().
3. Voeg styles toe in een `styles/` subfolder als de plugin
   QGIS-lagen oplevert.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "packages" / "lesa" / "lesa" / "plugins"


PLUGIN_YAML_TEMPLATE = dedent("""\
    id: {plugin_id}
    version: "0.1.0"
    name: "{name}"
    description: "TODO: korte omschrijving wat deze plugin doet"
    rangorde_position: {rangorde}
    landscape_types: [{landscape}]
    prerequisites: []
    python_class: "lesa.plugins.{plugin_id}.plugin:{class_name}"
""")


PARAMS_TEMPLATE = dedent("""\
    \"\"\"Parameters voor de {plugin_id}-plugin.\"\"\"

    from __future__ import annotations

    from pydantic import Field

    from lesa.plugins._base import PluginParams


    class {class_name}Params(PluginParams):
        \"\"\"TODO: documenteer parameters.\"\"\"

        # Voorbeeld:
        # threshold: float = Field(0.5, ge=0.0, le=1.0, description="...")
        # include_grondwater: bool = True
""")


PLUGIN_TEMPLATE = dedent("""\
    \"\"\"{name} — TODO: methodologische context.\"\"\"

    from __future__ import annotations

    from lesa.domain.scope import ScopeStatement
    from lesa.plugins._base import (
        PluginInputs,
        PluginOutputs,
        PluginRawData,
    )
    from lesa.plugins.{plugin_id}.params import {class_name}Params


    class {class_name}:
        PLUGIN_ID = "{plugin_id}"
        PLUGIN_VERSION = "0.1.0"
        PARAMS_CLASS = {class_name}Params

        @classmethod
        def params_schema(cls) -> dict:
            return cls.PARAMS_CLASS.params_schema()

        def validate_inputs(self, inputs: PluginInputs) -> None:
            # TODO: optioneel — controleer of alle vereiste prior_claims aanwezig zijn
            pass

        async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
            # TODO: data ophalen via geo_stack-skills (NIET httpx/requests rechtstreeks)
            return PluginRawData()

        def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
            # TODO: GIS-/statistiek-analyse, claims, hypothesen genereren
            return PluginOutputs(
                plugin_id=self.PLUGIN_ID,
                plugin_version=self.PLUGIN_VERSION,
                claims=[],
                hypotheses=[],
                scope=ScopeStatement(
                    scope="plugin",
                    subject_id=self.PLUGIN_ID,
                    based_on=[],
                    not_tested=["TODO"],
                    uncertainty_level="hoog",
                    consequences="Plugin nog niet geïmplementeerd.",
                ),
            )
""")


TEST_TEMPLATE = dedent("""\
    \"\"\"Smoke-test voor de {plugin_id}-plugin.\"\"\"

    from __future__ import annotations

    import pytest

    from lesa.plugins.{plugin_id}.plugin import {class_name}
    from lesa.plugins._base import Plugin


    def test_protocol_compliance():
        instance = {class_name}()
        assert isinstance(instance, Plugin)
        assert instance.PLUGIN_ID == "{plugin_id}"


    def test_params_schema():
        schema = {class_name}.params_schema()
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"
""")


def to_class_name(plugin_id: str) -> str:
    return "".join(part.capitalize() for part in plugin_id.split("_")) + "Plugin"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_id", help="snake_case id, bv. 'kwelkansenkaart'")
    parser.add_argument(
        "--rangorde",
        type=int,
        choices=[1, 2, 3, 4, 5, 6, 7],
        required=True,
        help="rangorde-positie (1=geologie, 7=mens)",
    )
    parser.add_argument(
        "--landscape",
        default="all",
        help="komma-gescheiden landschapstypen, default 'all'",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="leesbare naam voor in plugin.yaml; default = afgeleid van plugin_id",
    )

    args = parser.parse_args()

    plugin_id = args.plugin_id
    if not plugin_id.replace("_", "").isalnum() or not plugin_id.islower():
        print(f"Fout: plugin_id moet snake_case zijn, kreeg '{plugin_id}'", file=sys.stderr)
        return 1

    plugin_dir = PLUGINS_DIR / plugin_id
    if plugin_dir.exists():
        print(f"Fout: {plugin_dir} bestaat al", file=sys.stderr)
        return 1

    class_name = to_class_name(plugin_id)
    name = args.name or plugin_id.replace("_", " ").capitalize()
    landscape_list = ", ".join(repr(lt.strip()) for lt in args.landscape.split(","))

    plugin_dir.mkdir(parents=True)
    (plugin_dir / "tests").mkdir()

    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    (plugin_dir / "plugin.yaml").write_text(
        PLUGIN_YAML_TEMPLATE.format(
            plugin_id=plugin_id,
            name=name,
            rangorde=args.rangorde,
            landscape=landscape_list,
            class_name=class_name,
        ),
        encoding="utf-8",
    )

    (plugin_dir / "params.py").write_text(
        PARAMS_TEMPLATE.format(plugin_id=plugin_id, class_name=class_name),
        encoding="utf-8",
    )

    (plugin_dir / "plugin.py").write_text(
        PLUGIN_TEMPLATE.format(plugin_id=plugin_id, name=name, class_name=class_name),
        encoding="utf-8",
    )

    (plugin_dir / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "tests" / f"test_{plugin_id}.py").write_text(
        TEST_TEMPLATE.format(plugin_id=plugin_id, class_name=class_name),
        encoding="utf-8",
    )

    print(f"Plugin scaffold aangemaakt in {plugin_dir.relative_to(ROOT)}")
    print("Volgende stappen:")
    print(f"  1. Bewerk plugin.yaml — pas description en landscape_types aan")
    print(f"  2. Implementeer params.py + plugin.py")
    print(f"  3. uv run pytest packages/lesa/lesa/plugins/{plugin_id}/tests/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
