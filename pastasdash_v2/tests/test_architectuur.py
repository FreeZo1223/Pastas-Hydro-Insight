"""Bewaakt de scheiding tussen motor (``core``) en schil (``ui``).

Zonder zo'n test verwatert die scheiding vanzelf: één ``ui.notify`` in een
rekenfunctie en de motor is niet meer bruikbaar vanuit een notebook, script
of toekomstige andere frontend. Deze test faalt zodra dat gebeurt.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "pastasdash_v2"
CORE_DIR = PACKAGE_ROOT / "core"
UI_DIR = PACKAGE_ROOT / "ui"

VERBODEN_IN_CORE = {"nicegui", "pastasdash_v2.ui"}


def _geimporteerde_modules(pad: Path) -> set[str]:
    """Alle module-namen die een bestand importeert (top-level én lokaal)."""
    boom = ast.parse(pad.read_text(encoding="utf-8"), filename=str(pad))
    namen: set[str] = set()
    for node in ast.walk(boom):
        if isinstance(node, ast.Import):
            namen.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            namen.add(node.module)
    return namen


def _python_bestanden(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.unit
class TestMotorIsUIVrij:
    """``core`` moet bruikbaar zijn zonder dat er een browser aan te pas komt."""

    @pytest.mark.parametrize(
        "bestand", _python_bestanden(CORE_DIR), ids=lambda p: p.name
    )
    def test_core_importeert_geen_ui(self, bestand: Path):
        gevonden = _geimporteerde_modules(bestand)
        overtredingen = {
            naam
            for naam in gevonden
            for verboden in VERBODEN_IN_CORE
            if naam == verboden or naam.startswith(f"{verboden}.")
        }
        assert not overtredingen, (
            f"{bestand.relative_to(PACKAGE_ROOT)} importeert {sorted(overtredingen)}. "
            "De motor moet los van de UI bruikbaar blijven — verplaats deze code "
            "naar pastasdash_v2/ui/ of geef het resultaat terug in plaats van het "
            "zelf te tonen."
        )

    def test_core_is_importeerbaar_zonder_nicegui(self):
        """Importeren van de motor mag NiceGUI niet binnentrekken."""
        import subprocess
        import sys

        script = (
            "import sys;"
            "import pastasdash_v2.core.statistics;"
            "import pastasdash_v2.core.timeseries;"
            "import pastasdash_v2.core.store;"
            "sys.exit(1 if 'nicegui' in sys.modules else 0)"
        )
        resultaat = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True
        )
        assert resultaat.returncode == 0, (
            "Het importeren van pastasdash_v2.core trekt nicegui mee.\n"
            f"stderr: {resultaat.stderr}"
        )


@pytest.mark.unit
class TestSchilGebruiktMotor:
    """De schil mag de motor gebruiken; andersom niet."""

    def test_ui_bestaat_en_bevat_paginas(self):
        paginas = _python_bestanden(UI_DIR / "pages")
        assert len(paginas) > 1, "Verwacht meerdere pagina's in ui/pages."

    def test_geen_enkele_module_importeert_zichzelf_kruislings(self):
        """core mag ui niet importeren — expliciet, ook al dekt bovenstaande dit."""
        for bestand in _python_bestanden(CORE_DIR):
            tekst = bestand.read_text(encoding="utf-8")
            assert "pastasdash_v2.ui" not in tekst, (
                f"{bestand.name} verwijst naar de UI-laag."
            )
