"""Resultaatkaart: kleur peilbuizen op fit-stat (R², EVP) of GxG."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from nicegui import ui

from pastasdash_v2.components.header import render_header
from pastasdash_v2.components.plots import empty_figure
from pastasdash_v2.compute.timeseries import gxg, model_summary
from pastasdash_v2.state.store import STORE
from pastasdash_v2.tasks import run_in_thread

log = logging.getLogger(__name__)

_METRIC_OPTIONS = {
    "rsq": "R² (modelkwaliteit)",
    "evp": "EVP (modelkwaliteit)",
    "ghg": "GHG",
    "glg": "GLG",
    "gvg": "GVG",
    "n_observations": "Aantal observaties",
}


def render() -> None:
    render_header(active_tab="maps")
    if not STORE.is_loaded:
        with ui.card().classes("w-full max-w-xl mx-auto mt-8"):
            ui.label("Laad eerst een PastaStore op de Start-pagina.").classes("text-lg")
            ui.link("→ Start", target="/").classes("text-blue-600")
        return

    ui_state = STORE.ui_state
    metric = ui_state.get("maps.metric", "rsq")

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("items-center gap-3"):
            ui.label("Toon op kaart:").classes("font-medium")
            select = ui.select(
                options=_METRIC_OPTIONS, value=metric
            ).classes("min-w-64")
            colormap = ui.select(
                ["Viridis", "Plasma", "RdYlGn", "Blues"],
                value=ui_state.get("maps.cmap", "Viridis"),
                label="Kleurschaal",
            ).classes("min-w-40")
            reverse = ui.switch("Inverteren", value=ui_state.get("maps.reverse", False))

        plot_holder = ui.column().classes("w-full")

        async def _redraw() -> None:
            ui_state.set("maps.metric", select.value)
            ui_state.set("maps.cmap", colormap.value)
            ui_state.set("maps.reverse", reverse.value)
            df = await run_in_thread(
                "Statistieken verzamelen", _collect_metric, select.value
            )
            plot_holder.clear()
            with plot_holder:
                if df.empty:
                    ui.plotly(empty_figure("Geen data voor deze statistiek")).classes("w-full")
                    return
                ui.plotly(_build_choropleth(df, select.value, colormap.value, reverse.value)).classes("w-full")

        select.on_value_change(lambda _e: _redraw())
        colormap.on_value_change(lambda _e: _redraw())
        reverse.on_value_change(lambda _e: _redraw())

        # initial render asynchroon
        ui.timer(0.1, _redraw, once=True)


def _collect_metric(metric: str) -> pd.DataFrame:
    df = STORE.oseries().copy()
    if df.empty:
        return df

    values: list[float] = []
    for name in df.index:
        v = np.nan
        try:
            if metric in ("rsq", "evp"):
                if name in STORE.model_names():
                    s = model_summary(STORE.store_key, name)
                    v = float(s.get(metric, np.nan))
            elif metric in ("ghg", "glg", "gvg"):
                g = gxg(STORE.store_key, name)
                v = float(g.get(metric.upper(), np.nan))
            elif metric == "n_observations":
                v = float(df.loc[name].get("n_observations", np.nan))
        except Exception:  # noqa: BLE001
            v = np.nan
        values.append(v)
    df["metric_value"] = values
    return df


def _build_choropleth(df: pd.DataFrame, metric: str, cmap: str, reverse: bool) -> go.Figure:
    series = df["metric_value"]
    if series.dropna().empty:
        return empty_figure(f"Geen waarden voor {metric}")
    fig = go.Figure(
        go.Scattermapbox(
            lat=df["lat"], lon=df["lon"], text=df.index,
            mode="markers",
            marker=dict(
                size=10, color=series, colorscale=cmap, reversescale=reverse,
                showscale=True, colorbar=dict(title=metric.upper()),
            ),
            hovertemplate="<b>%{text}</b><br>" + metric + "=%{marker.color:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_center=dict(lat=float(df["lat"].mean()), lon=float(df["lon"].mean())),
        mapbox_zoom=8,
        margin=dict(l=0, r=0, t=0, b=0), height=600,
    )
    return fig
