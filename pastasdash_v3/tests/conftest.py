"""Gedeelde opzet voor de tests van de rekenlaag.

De rekenkern van v2 bewaart instellingen en tussenresultaten in de thuismap
van de gebruiker. Tests mogen die niet aanraken: daarom wijst de thuismap
hier naar een tijdelijke map, vóórdat de kern wordt geladen.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_thuis = tempfile.mkdtemp(prefix="pastasdash_v3_test_")
os.environ["USERPROFILE"] = _thuis
os.environ["HOME"] = _thuis

_v3 = Path(__file__).resolve().parents[1]
for pad in (_v3, _v3.parent / "pastasdash_v2"):
    if str(pad) not in sys.path:
        sys.path.insert(0, str(pad))
