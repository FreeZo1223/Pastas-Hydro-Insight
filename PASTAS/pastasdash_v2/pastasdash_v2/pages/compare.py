"""Vergelijk-pagina: meerdere modellen naast elkaar."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
from nicegui import ui

from pastasdash_v2.components.header import render_header
from pastasdash_v2.components.plots import clean_fig, empty_figure
from pastasdash_v2.compute.timeseries import model_summary
from pastasdash_v2.state.store import STORE

log = logging.getLogger(__name__)


def render() -> None:
    render_header(active_tab="compare")
    if not STORE.is_loaded:
        with ui.card().classes("w-full max-w-xl mx-auto mt-8"):
            ui.label("Laad eerst een PastaStore op de Start-pagina.").classes("text-lg")
            ui.link("→ Start", target="/").classes("text-blue-600")
        return

    ui_state = STORE.ui_state
    model_names = STORE.model_names()
    if not model_names:
        with ui.column().classes("w-full p-4"):
            ui.label("Geen gefitte modellen in deze store.").classes("opacity-75")
            ui.label("Fit eerst modellen op de Model-pagina.").classes("opacity-75")
        return

    selected: list[str] = ui_state.get("compare.selected", model_names[:3] if len(model_names) >= 3 else model_names) or []

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("items-center gap-3"):
            ui.label("Modellen om te vergelijken:").classes("font-medium")
            select = (
                ui.select(options=model_names, value=selected, multiple=True, with_input=True)
                .classes("min-w-96")
            )

        chart_holder = ui.column().classes("w-full")
        table_holder = ui.column().classes("w-full")

        def _redraw() -> None:
            chart_holder.clear()
            table_holder.clear()
            names = select.value or []
            ui_state.set("compare.selected", list(names))
            if not names:
                with chart_holder:
                    ui.plotly(clean_fig(empty_figure("Selecteer minimaal één model"))).classes("w-full")
                return

            # vergelijking-chart: alle simulaties + obs
            fig = go.Figure()
            for n in names:
                try:
                    ml = STORE.pstore.get_models(n)
                    fig.add_trace(go.Scatter(
                        x=ml.observations().index, y=ml.observations().values,
                        name=f"{n} obs", mode="markers", marker=dict(size=3),
                    ))
                    sim = ml.simulate()
                    fig.add_trace(go.Scatter(
                        x=sim.index, y=sim.values, name=f"{n} sim", mode="lines",
                    ))
                except Exception as exc:  # noqa: BLE001
                    log.warning("Model %s niet plotbaar: %s", n, exc)
            fig.update_layout(
                template="plotly_white", height=520, hovermode="x unified",
                margin=dict(l=20, r=20, t=30, b=30),
                legend=dict(orientation="h", y=-0.15),
                yaxis_title="m NAP",
            )
            with chart_holder:
                ui.plotly(clean_fig(fig)).classes("w-full")

            # samenvattingstabel
            rows = []
            for n in names:
                s = model_summary(STORE.store_key, n)
                rows.append({
                    "model": n,
                    "rsq": round(s.get("rsq", float("nan")), 3) if s.get("rsq") is not None else "",
                    "evp": round(s.get("evp", float("nan")), 1) if s.get("evp") is not None else "",
                    "n_obs": s.get("n_obs", ""),
                    "tmin": (s.get("tmin") or "")[:10],
                    "tmax": (s.get("tmax") or "")[:10],
                })
            cols = [
                {"name": "model", "label": "Model", "field": "model", "sortable": True, "align": "left"},
                {"name": "rsq", "label": "R²", "field": "rsq", "sortable": True},
                {"name": "evp", "label": "EVP %", "field": "evp", "sortable": True},
                {"name": "n_obs", "label": "N", "field": "n_obs", "sortable": True},
                {"name": "tmin", "label": "tmin", "field": "tmin"},
                {"name": "tmax", "label": "tmax", "field": "tmax"},
            ]
            with table_holder:
                ui.table(columns=cols, rows=rows, row_key="model").classes("w-full")

        select.on_value_change(lambda _e: _redraw())
        _redraw()
