"""Start-pagina: store-laden + samenvatting."""

from __future__ import annotations

from nicegui import ui

from pastasdash_v2.components.header import render_header
from pastasdash_v2.components.store_loader import render_store_loader
from pastasdash_v2.state.store import STORE


def render() -> None:
    render_header(active_tab="home")
    with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
        ui.label("Welkom").classes("text-2xl font-medium")
        ui.markdown(
            "PastasDash v2 ondersteunt drie input-formaten:\n"
            "1. **Native PastaStore-ZIP** (`.pastastore` of `.zip` gemaakt door PASTAS)\n"
            "2. **BRO Loket export-ZIP** (auto-conversie naar PastaStore + KNMI-fetch)\n"
            "3. **Uitgepakte BRO Loket-map** (volledig pad op schijf)"
        )

        render_store_loader()

        # samenvatting wanneer geladen
        summary_container = ui.column().classes("w-full mt-4")

        def _refresh_summary() -> None:
            summary_container.clear()
            with summary_container:
                if not STORE.is_loaded:
                    return
                with ui.card().classes("w-full"):
                    ui.label("Store-samenvatting").classes("text-lg font-medium")
                    pstore = STORE.pstore
                    with ui.row().classes("gap-8"):
                        with ui.column():
                            ui.label("Peilbuizen (oseries)").classes("text-sm opacity-75")
                            ui.label(str(len(pstore.oseries_names))).classes("text-2xl font-medium")
                        with ui.column():
                            ui.label("Stress-reeksen").classes("text-sm opacity-75")
                            ui.label(str(len(pstore.stresses_names))).classes("text-2xl font-medium")
                        with ui.column():
                            ui.label("Modellen").classes("text-sm opacity-75")
                            ui.label(str(len(pstore.model_names))).classes("text-2xl font-medium")

                    ui.separator()
                    ui.label("Ga naar een tab in de header om verder te werken.").classes("text-sm opacity-75")

        _refresh_summary()
        STORE.on_change(_refresh_summary)
