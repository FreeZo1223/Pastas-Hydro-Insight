"""NiceGUI applicatie-entry: registreert alle pages."""

from __future__ import annotations

import logging

from nicegui import app, ui

from pastasdash_v2.core.config import APP_NAME, BRAND_COLOR, DEFAULT_PORT
from pastasdash_v2.core.store import restore_last_store
from pastasdash_v2.ui.pages import (
    compare,
    droogte,
    home,
    maps,
    model,
    overview,
    statistics,
)

log = logging.getLogger(__name__)


def run(host: str = "127.0.0.1", port: int = DEFAULT_PORT, reload: bool = False) -> None:
    """Start de NiceGUI server."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    try:
        restore_last_store()
    except Exception as exc:  # noqa: BLE001
        log.warning("Restore-laatste-store faalde: %s", exc)

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

    @ui.page("/statistics")
    def page_statistics() -> None:
        statistics.render()

    # ui.colors() mag niet vóór ui.run() worden aangeroepen: dat zet NiceGUI's
    # script_mode aan en laat ui.run() vervolgens crashen op de @ui.page-routes
    # hierboven. Per pagina zet apply_theme() de kleuren nogmaals; deze regel
    # dekt de korte periode vóór de eerste render.
    app.on_startup(lambda: ui.colors(primary=BRAND_COLOR))
    ui.run(
        host=host, port=port, title="PastasDash",
        reload=reload, show=False, storage_secret=APP_NAME,
    )
