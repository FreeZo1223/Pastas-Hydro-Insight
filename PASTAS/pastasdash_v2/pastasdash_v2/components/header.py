"""Header: titel, store-naam, navigatie-tabs, achtergrond-takenindicator."""

from __future__ import annotations

from nicegui import ui

from pastasdash_v2.config import BRAND_COLOR
from pastasdash_v2.state.store import STORE
from pastasdash_v2.tasks import REGISTRY


def render_header(active_tab: str = "overview") -> None:
    """Render top-header met store-info en taken-indicator."""
    with ui.header().classes("items-center justify-between").style(
        f"background-color: {BRAND_COLOR}; color: white; padding: 8px 16px;"
    ):
        with ui.row().classes("items-center gap-4"):
            ui.icon("water_drop").classes("text-2xl")
            ui.label("PastasDash v2").classes("text-xl font-medium")
            store_label = ui.label().classes("text-sm opacity-90")

            def _refresh_store_label() -> None:
                if STORE.is_loaded:
                    store_label.text = f"— {STORE.display_name}"
                else:
                    store_label.text = "— (geen store geladen)"

            _refresh_store_label()
            STORE.on_change(_refresh_store_label)

        # rechts: taken-indicator + nav links
        with ui.row().classes("items-center gap-4"):
            _render_task_indicator()
            _render_nav(active_tab)


def _render_task_indicator() -> None:
    """Toon spinner + label van lopende achtergrondtaken."""
    container = ui.row().classes("items-center gap-2")

    def _refresh() -> None:
        container.clear()
        with container:
            if len(REGISTRY) == 0:
                ui.icon("check_circle").classes("text-green-300 text-sm")
                ui.label("idle").classes("text-xs opacity-75")
            else:
                ui.spinner(size="sm", color="white")
                labels = REGISTRY.labels()
                first = labels[0]
                extra = f" (+{len(labels) - 1})" if len(labels) > 1 else ""
                ui.label(f"{first}{extra}").classes("text-xs")

    _refresh()
    REGISTRY.on_change(lambda: ui.timer(0.01, _refresh, once=True))
    ui.timer(1.0, _refresh)  # safety: refresh elke seconde


def _render_nav(active: str) -> None:
    """Tab-navigatie als linkjes (NiceGUI page-routing)."""
    pages = [
        ("home", "Start", "home"),
        ("overview", "Overzicht", "map"),
        ("model", "Model", "show_chart"),
        ("compare", "Vergelijken", "compare"),
        ("maps", "Resultaatkaart", "layers"),
        ("droogte", "Droogte", "water_drop"),
    ]
    for slug, label, icon in pages:
        is_active = slug == active
        cls = "text-white font-medium" if is_active else "text-white opacity-75 hover:opacity-100"
        with ui.link(target=f"/{slug}" if slug != "home" else "/").classes(cls):
            with ui.row().classes("items-center gap-1"):
                ui.icon(icon).classes("text-sm")
                ui.label(label)
