"""Overzicht-pagina: kaart + tabel + tijdreeks-plot van geselecteerde peilbuizen."""

from __future__ import annotations

import logging

from nicegui import ui

from pastasdash_v2.components.header import render_header
from pastasdash_v2.components.plots import (
    empty_figure, map_oseries, timeseries_overlay, timeseries_stacked,
)
from pastasdash_v2.compute.timeseries import get_oseries, get_stress
from pastasdash_v2.state.store import STORE
from pastasdash_v2.tasks import run_in_thread

log = logging.getLogger(__name__)


def render() -> None:
    render_header(active_tab="overview")
    with ui.column().classes("w-full p-4 gap-4"):
        if not STORE.is_loaded:
            _render_empty_state()
            return

        ui_state = STORE.ui_state
        selected: list[str] = ui_state.get("overview.selected", []) or []
        layout_mode: str = ui_state.get("overview.layout", "overlay") or "overlay"
        show_stresses: bool = ui_state.get("overview.show_stresses", False) or False

        df = STORE.oseries()

        with ui.row().classes("w-full gap-4"):
            # ── Linkerkolom: kaart + tabel ───────────────────────────────
            with ui.column().classes("flex-1 min-w-0"):
                ui.label("Kaart").classes("text-lg font-medium")
                map_fig = map_oseries(df, selected=selected)
                map_plot = ui.plotly(map_fig).classes("w-full")

                ui.label("Peilbuizen").classes("text-lg font-medium mt-4")

                rows = [
                    {
                        "name": name,
                        "n": int(row.get("n_observations", 0) or 0),
                        "z": round(float(row.get("z", 0) or 0), 2) if row.get("z") is not None else "",
                    }
                    for name, row in df.iterrows()
                ]
                cols = [
                    {"name": "name", "label": "Naam", "field": "name", "sortable": True, "align": "left"},
                    {"name": "n",    "label": "N obs", "field": "n", "sortable": True},
                    {"name": "z",    "label": "Filter midden (m NAP)", "field": "z", "sortable": True},
                ]
                table = ui.table(columns=cols, rows=rows, row_key="name", selection="multiple").classes(
                    "w-full h-96"
                )
                table.selected = [{"name": n} for n in selected if n in df.index]

            # ── Rechterkolom: plot + controls ─────────────────────────────
            with ui.column().classes("flex-1 min-w-0"):
                with ui.row().classes("items-center gap-4 w-full"):
                    layout_radio = ui.radio(
                        ["overlay", "stacked"], value=layout_mode
                    ).props("inline").classes("text-sm")
                    stress_toggle = ui.switch("Stresses tonen", value=show_stresses)

                plot_holder = ui.column().classes("w-full")

                def _redraw() -> None:
                    plot_holder.clear()
                    with plot_holder:
                        if not selected:
                            ui.plotly(empty_figure("Selecteer peilbuizen in de kaart of tabel.")).classes(
                                "w-full"
                            )
                            return
                        series = {name: get_oseries(name) for name in selected}
                        if stress_toggle.value:
                            for sname in STORE.pstore.stresses_names:
                                try:
                                    series[f"[stress] {sname}"] = get_stress(sname)
                                except Exception:  # noqa: BLE001
                                    continue
                        fig = (
                            timeseries_stacked(series)
                            if layout_radio.value == "stacked"
                            else timeseries_overlay(series)
                        )
                        ui.plotly(fig).classes("w-full")

                def _on_table_select() -> None:
                    nonlocal selected
                    selected = [r["name"] for r in table.selected]
                    ui_state.set("overview.selected", selected)
                    # update kaart
                    map_plot.figure = map_oseries(df, selected=selected)
                    map_plot.update()
                    _redraw()

                def _on_layout_change() -> None:
                    ui_state.set("overview.layout", layout_radio.value)
                    _redraw()

                def _on_stress_toggle() -> None:
                    ui_state.set("overview.show_stresses", stress_toggle.value)
                    _redraw()

                table.on("selection", _on_table_select)
                layout_radio.on_value_change(_on_layout_change)
                stress_toggle.on_value_change(_on_stress_toggle)

                _redraw()


def _render_empty_state() -> None:
    with ui.card().classes("w-full max-w-2xl mx-auto"):
        ui.icon("info", size="2em").classes("text-blue-500")
        ui.label("Nog geen PastaStore geladen").classes("text-xl font-medium")
        ui.label("Ga naar Start om een store te laden.").classes("opacity-75")
        ui.link("→ Naar Start", target="/").classes("text-blue-600 mt-2")
