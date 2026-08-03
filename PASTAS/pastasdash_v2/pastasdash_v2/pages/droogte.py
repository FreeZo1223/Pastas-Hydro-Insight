"""Droogte-pagina: cumulatief neerslagtekort met percentielbanden + vergelijkingsjaren."""

from __future__ import annotations

import logging
from datetime import date

from nicegui import ui

from pastasdash_v2.components.header import render_header
from pastasdash_v2.components.plots import clean_fig, empty_figure, droogte_figure
from pastasdash_v2.compute import droogte as droogte_compute
from pastasdash_v2.compute.knmi import fetch_knmi_daily
from pastasdash_v2.compute.stations import DEFAULT_STATION_CODE, STATIONS_BY_CODE, station_label_map
from pastasdash_v2.state.persistence import AppState
from pastasdash_v2.tasks import run_in_thread

log = logging.getLogger(__name__)

_DEFAULT_REF_START = 1990
_DEFAULT_REF_END = 2020
_DEFAULT_CMP_YEARS: list[int] = [2018, 2020, 2024]


def render() -> None:
    render_header(active_tab="droogte")

    # Persistente UI-state — gebruikt AppState (niet per-store) want droogte
    # is store-onafhankelijk
    station = AppState.get("droogte.station", DEFAULT_STATION_CODE)
    ref_start = AppState.get("droogte.ref_start", _DEFAULT_REF_START)
    ref_end = AppState.get("droogte.ref_end", _DEFAULT_REF_END)
    cmp_years = AppState.get("droogte.cmp_years", _DEFAULT_CMP_YEARS) or _DEFAULT_CMP_YEARS
    clip_neg = AppState.get("droogte.clip_neg", True)

    with ui.row().classes("w-full p-4 gap-4"):
        # ── Sidebar ──────────────────────────────────────────────────────
        with ui.column().classes("w-72 flex-shrink-0"):
            with ui.card().classes("w-full"):
                ui.label("Instellingen").classes("text-lg font-medium")

                station_sel = ui.select(
                    options=station_label_map(), value=station, label="KNMI-station"
                ).classes("w-full")

                with ui.row().classes("gap-2"):
                    ref_from = ui.number(label="Ref vanaf", value=ref_start, format="%.0f").classes("w-28")
                    ref_to = ui.number(label="Ref tot", value=ref_end, format="%.0f").classes("w-28")

                cmp_input = ui.input(
                    label="Vergelijk jaren (komma-gescheiden)",
                    value=",".join(str(y) for y in cmp_years),
                ).classes("w-full")

                clip_switch = ui.switch("Knip negatieve waarden", value=clip_neg)
                ui.button("Vernieuwen", icon="refresh", on_click=lambda: _trigger()).props(
                    "color=primary"
                ).classes("w-full mt-2")

        # ── Plot ──────────────────────────────────────────────────────────
        with ui.column().classes("flex-1 min-w-0"):
            ui.label("Cumulatief neerslagtekort").classes("text-lg font-medium")
            plot_holder = ui.column().classes("w-full")
            with plot_holder:
                ui.plotly(clean_fig(empty_figure("Klik 'Vernieuwen' om de plot te bouwen."))).classes("w-full")

        async def _compute_and_plot() -> None:
            # parse + persist
            stn = int(station_sel.value)
            rs = int(ref_from.value)
            re_ = int(ref_to.value)
            try:
                cmp_list = [int(s.strip()) for s in (cmp_input.value or "").split(",") if s.strip()]
            except ValueError:
                ui.notify("Vergelijkjaren moet komma-lijst van jaartallen zijn.", type="warning")
                return
            cn = bool(clip_switch.value)

            AppState.set("droogte.station", stn)
            AppState.set("droogte.ref_start", rs)
            AppState.set("droogte.ref_end", re_)
            AppState.set("droogte.cmp_years", cmp_list)
            AppState.set("droogte.clip_neg", cn)

            station_obj = STATIONS_BY_CODE.get(stn)
            label = station_obj.name if station_obj else str(stn)

            try:
                df = await run_in_thread(
                    f"KNMI ophalen ({label})", fetch_knmi_daily, stn, rs, notify=False
                )
            except Exception as exc:  # noqa: BLE001
                ui.notify(f"KNMI-fetch faalde: {exc}", type="negative", timeout=8000)
                return

            # compute
            deficit = droogte_compute.daily_deficit(df["RH"], df["EV24"])
            cum = droogte_compute.cumulative_deficit_by_doy(deficit, clip_negative=cn)
            pivot = droogte_compute.pivot_by_doy(cum)
            ref_pivot = droogte_compute.select_reference_years(pivot, rs, re_)
            bands = droogte_compute.percentile_bands(ref_pivot)
            current = droogte_compute.current_year_series(cum)
            comparisons = droogte_compute.comparison_year_series(cum, cmp_list)

            fig = droogte_figure(
                bands=bands, current=current, comparisons=comparisons,
                title=f"Neerslagtekort {label} (ref {rs}–{re_})",
            )
            plot_holder.clear()
            with plot_holder:
                ui.plotly(clean_fig(fig)).classes("w-full")

        def _trigger() -> None:
            ui.timer(0.01, _compute_and_plot, once=True)

        # auto-compute bij eerste laad als state aanwezig
        if AppState.get("droogte.last_run"):
            ui.timer(0.2, _compute_and_plot, once=True)
        AppState.set("droogte.last_run", date.today().isoformat())
