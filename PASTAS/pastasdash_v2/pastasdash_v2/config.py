"""Configuratie en paden voor PastasDash v2."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "pastasdash_v2"
APP_DIR = Path.home() / f".{APP_NAME}"
APP_DIR.mkdir(parents=True, exist_ok=True)

STATE_DB_PATH = APP_DIR / "state.db"
COMPUTE_CACHE_DIR = APP_DIR / "cache"
KNMI_CACHE_DIR = APP_DIR / "knmi_cache"

for d in (COMPUTE_CACHE_DIR, KNMI_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

BRAND_COLOR = "#006f92"
ACCENT_COLOR = "#f7a31c"

DEFAULT_PORT = 8051  # 8050 is voor de oude pastasdash; voorkom conflict

CRS_RD = "EPSG:28992"
CRS_WGS84 = "EPSG:4326"


@dataclass(frozen=True)
class ColumnMapping:
    """Welke kolommen in PastaStore.oseries de hydrologische metadata bevatten."""

    x: str = "x"
    y: str = "y"
    screen_top: str = "screen_top"
    screen_bottom: str = "screen_bottom"
    ground_level: str = "ground_level"


DEFAULT_COLUMNS = ColumnMapping()
