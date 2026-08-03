"""Reeksen: de geselecteerde peilbuizen als tijdreeks, met de kaart erbij.

De peilbuiskeuze gebeurt in de zijbalk (zie ``ui/shell.py``) en niet meer in
een tabel op deze pagina — dat leverde twee selecties op die uit de pas liepen.
"""

from __future__ import annotations

import logging

from nicegui import ui

from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import get_oseries, get_stress
from pastasdash_v2.ui.components.plots import (
    clean_fig,
    empty_figure,
    map_oseries,
    timeseries_overlay,
    timeseries_stacked,
)
from pastasdash_v2.ui.shell import geselecteerd, pagina

log = logging.getLogger(__name__)


def render() -> None:
    with pagina("overview"):
        if not STORE.is_loaded:
            geen_dataset()
            return

        selectie = geselecteerd()
        if not selectie:
            niets_geselecteerd()
            return

        ui_state = STORE.ui_state
        modus = ui_state.get("overview.layout", "overlay") or "overlay"
        toon_stress = bool(ui_state.get("overview.show_stresses", False))

        with ui.row().classes("items-center justify-between w-full no-wrap"):
            with ui.column().classes("gap-1"):
                ui.label("Grondwaterstand").classes("peil-label")
                ui.label(
                    f"{len(selectie)} reeks" + ("" if len(selectie) == 1 else "en")
                ).classes("text-sm").style("color: var(--peil-slate)")
            with ui.row().classes("items-center gap-5 no-wrap"):
                keuze = ui.toggle(
                    {"overlay": "Over elkaar", "stacked": "Onder elkaar"}, value=modus
                ).props("dense no-caps unelevated")
                schakelaar = ui.switch("Neerslag en verdamping", value=toon_stress)

        grafiek = ui.column().classes("w-full peil-card p-3")

        def _teken() -> None:
            grafiek.clear()
            with grafiek:
                reeksen = {}
                for naam in selectie:
                    try:
                        reeksen[naam] = get_oseries(naam)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Reeks %s niet leesbaar: %s", naam, exc)
                if schakelaar.value:
                    for stress in STORE.pstore.stresses_names:
                        try:
                            reeksen[stress] = get_stress(stress)
                        except Exception:  # noqa: BLE001
                            continue
                if not reeksen:
                    ui.plotly(
                        clean_fig(empty_figure("Deze reeksen bevatten geen metingen."))
                    ).classes("w-full")
                    return
                figuur = (
                    timeseries_stacked(reeksen)
                    if keuze.value == "stacked"
                    else timeseries_overlay(reeksen)
                )
                ui.plotly(clean_fig(figuur)).classes("w-full")

        def _bewaar_modus() -> None:
            ui_state.set("overview.layout", keuze.value)
            _teken()

        def _bewaar_stress() -> None:
            ui_state.set("overview.show_stresses", schakelaar.value)
            _teken()

        keuze.on_value_change(_bewaar_modus)
        schakelaar.on_value_change(_bewaar_stress)
        _teken()
        _kaart(selectie)


def _kaart(selectie: list[str]) -> None:
    df = STORE.oseries()
    if df.empty or df["lat"].isna().all():
        return
    with ui.column().classes("w-full peil-card p-3 gap-2"):
        ui.label("Ligging").classes("peil-label")
        ui.plotly(clean_fig(map_oseries(df, selected=selectie))).classes("w-full")


def geen_dataset() -> None:
    """Lege staat die naar de volgende stap wijst in plaats van alleen te melden."""
    with ui.column().classes("peil-card p-6 gap-3 w-full max-w-xl"):
        ui.label("Nog geen dataset").classes("text-base font-semibold")
        ui.label("Laad eerst een dataset met peilbuisreeksen.").classes(
            "text-sm"
        ).style("color: var(--peil-slate)")
        ui.button("Dataset kiezen", on_click=lambda: ui.navigate.to("/")).props(
            "unelevated no-caps"
        )


def niets_geselecteerd(extra: str = "") -> None:
    with ui.column().classes("peil-card p-6 gap-2 w-full max-w-xl"):
        ui.label("Kies een peilbuis").classes("text-base font-semibold")
        ui.label(
            extra
            or "Selecteer links een of meer peilbuizen. Je keuze blijft staan als "
               "je naar een andere weergave gaat."
        ).classes("text-sm").style("color: var(--peil-slate); max-width: 52ch")
