"""NiceGUI applicatie-entry: registreert alle pages."""

from __future__ import annotations

import logging

from nicegui import app, ui

from pastasdash_v2.config import APP_NAME, BRAND_COLOR, DEFAULT_PORT
from pastasdash_v2.pages import compare, droogte, home, maps, model, overview
from pastasdash_v2.state.store import restore_last_store

log = logging.getLogger(__name__)


@ui.page("/")
def page_home() -> None:
    home.render()


@ui.page("/overview")
def page_overview() -> None:
    overview.render()


@ui.page("/model")
def page_model() -> None:
    model.render()


@ui.page("/compare")
def page_compare() -> None:
    compare.render()


@ui.page("/maps")
def page_maps() -> None:
    maps.render()


@ui.page("/droogte")
def page_droogte() -> None:
    droogte.render()


def run(host: str = "127.0.0.1", port: int = DEFAULT_PORT, reload: bool = False) -> None:
    """Start de NiceGUI server."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    # Probeer de laatst gebruikte store te restoren (synchrone load bij opstart)
    try:
        restore_last_store()
    except Exception as exc:  # noqa: BLE001
        log.warning("Restore-laatste-store faalde: %s", exc)

    ui.colors(primary=BRAND_COLOR)
    ui.run(
        host=host, port=port, title="PastasDash v2",
        reload=reload, show=False, storage_secret=APP_NAME,
    )
