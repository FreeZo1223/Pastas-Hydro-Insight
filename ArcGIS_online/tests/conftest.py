"""Pytest config: maak scripts/ importeerbaar als top-level modules."""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
