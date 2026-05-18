"""CI-validatie van alle plugin-yaml's en hun importeerbaarheid.

Gebruik:
    uv run python scripts/validate_plugins.py

Exitcode 0 = OK, 1 = fout(en) gevonden.
"""

from __future__ import annotations

import sys

from lesa.plugins._registry import PluginRegistry, PluginRegistryError


def main() -> int:
    registry = PluginRegistry()
    try:
        registry.load()
    except PluginRegistryError as exc:
        print(f"PLUGIN-REGISTRY FAALDE:\n{exc}", file=sys.stderr)
        return 1

    if len(registry) == 0:
        print("Geen plugins gevonden — dat is OK in vroege fase.")
        return 0

    print(f"Geladen: {len(registry)} plugin(s)\n")
    for meta in registry.list_plugins():
        print(
            f"  • {meta.id} v{meta.version} (rangorde {meta.rangorde_position}) — {meta.name}"
        )

    # Check dat elke plugin instantieerbaar is en het Protocol vervult
    errors: list[str] = []
    for meta in registry.list_plugins():
        try:
            instance = registry.get_instance(meta.id)
        except PluginRegistryError as exc:
            errors.append(f"{meta.id}: {exc}")
            continue

        # Verplichte attributen
        for attr in ("PLUGIN_ID", "PLUGIN_VERSION", "PARAMS_CLASS"):
            if not hasattr(instance, attr):
                errors.append(f"{meta.id}: mist attribuut {attr!r}")

        # Schema-call moet werken
        try:
            schema = instance.params_schema()
            if not isinstance(schema, dict) or schema.get("type") != "object":
                errors.append(
                    f"{meta.id}: params_schema() geeft geen geldige object-schema terug"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{meta.id}: params_schema() faalt — {exc}")

    if errors:
        print("\nFOUT:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    print("\nAlle plugins valide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
