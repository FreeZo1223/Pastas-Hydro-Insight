"""Startpagina: dataset kiezen en zien wat erin zit.

Bewust géén zijbalk: hier is nog niets om in te selecteren. Zodra een dataset
geladen is, wijst deze pagina door naar de weergaven.
"""

from __future__ import annotations

from nicegui import ui

from pastasdash_v2.core.store import STORE
from pastasdash_v2.ui.components.store_loader import render_store_loader
from pastasdash_v2.ui.theme import apply_theme


def render() -> None:
    apply_theme()

    with ui.header().classes("peil-rule").style(
        "background: var(--peil-surface); padding: 0 20px; height: 52px;"
    ):
        with ui.row().classes("items-center gap-3 no-wrap h-full"):
            ui.html(
                '<div style="width:3px;height:20px;background:var(--peil-brand);'
                'border-radius:1px"></div>'
            )
            ui.label("PastasDash").classes("text-base font-semibold")

    with ui.column().classes("w-full max-w-3xl mx-auto p-8 gap-6"):
        with ui.column().classes("gap-2"):
            ui.label("Grondwaterreeksen bekijken en modelleren").classes(
                "text-2xl font-semibold"
            ).style("color: var(--peil-ink); letter-spacing: -.01em")
            ui.label(
                "Kies een dataset met peilbuisreeksen. Daarna kun je reeksen "
                "vergelijken, PASTAS-modellen fitten en GxG-statistiek aflezen."
            ).classes("text-sm").style("color: var(--peil-slate); max-width: 60ch")

        render_store_loader()
        _samenvatting()


def _samenvatting() -> None:
    houder = ui.column().classes("w-full gap-4")

    def _ververs() -> None:
        houder.clear()
        with houder:
            if not STORE.is_loaded:
                return
            pstore = STORE.pstore
            with ui.column().classes("peil-card w-full p-5 gap-4"):
                ui.label("Inhoud").classes("peil-label")
                with ui.row().classes("gap-10 no-wrap"):
                    _kental("Peilbuizen", len(pstore.oseries_names))
                    _kental("Stressreeksen", len(pstore.stresses_names))
                    _kental("Modellen", len(pstore.model_names))

                if not pstore.model_names:
                    ui.label(
                        "Er zijn nog geen modellen. Fit ze onder Model, of bekijk "
                        "eerst de ruwe reeksen."
                    ).classes("text-sm").style("color: var(--peil-slate)")

            with ui.row().classes("gap-3"):
                ui.button(
                    "Naar de reeksen", on_click=lambda: ui.navigate.to("/overview")
                ).props("unelevated no-caps")
                ui.button(
                    "Naar de statistiek",
                    on_click=lambda: ui.navigate.to("/statistics"),
                ).props("outline no-caps")

    _ververs()
    STORE.on_change(_ververs)


def _kental(label: str, waarde: int) -> None:
    with ui.column().classes("gap-1"):
        ui.label(label).classes("peil-label")
        ui.label(str(waarde)).classes("peil-num peil-num-lg font-semibold")
