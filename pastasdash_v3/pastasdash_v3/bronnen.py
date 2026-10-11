"""Adressen en versies, uit ``bronnen.json``."""

from __future__ import annotations

import json
from pathlib import Path

_hier = Path(__file__).resolve().parent
# In de browser staat het bestand naast deze module, in de repo een map hoger.
_pad = next(p for p in (_hier / "bronnen.json", _hier.parent / "bronnen.json") if p.exists())

BRONNEN: dict = json.loads(_pad.read_text(encoding="utf-8"))
