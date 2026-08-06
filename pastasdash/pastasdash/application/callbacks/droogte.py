"""Callbacks voor het Droogte-tabblad.

Eén callback die de grafiek vernieuwt op basis van de sidebar-instellingen.
De zware berekening vindt plaats in droogte.compute en droogte.data.
"""

from __future__ import annotations

import logging

import plotly.graph_objs as go
from dash import Input, Output, State, no_update

from pastasdash.application.components.shared import ids
from pastasdash.application.droogte.compute import (
    comparison_year_series,
    cumulative_deficit_by_doy,
    current_year_series,
    daily_deficit,
    percentile_bands,
    pivot_by_doy,
    select_reference_years,
)
from pastasdash.application.droogte.data import fetch_knmi_daily
from pastasdash.application.droogte.stations import STATIONS_BY_CODE

_log = logging.getLogger(__name__)

# Kleuren
_COLOR_BAND_OUTER = "rgba(180,200,230,0.3)"   # p5-p95
_COLOR_BAND_INNER = "rgba(100,150,210,0.4)"   # p25-p75
_COLOR_MEDIAN = "#3366cc"
_COLOR_CURRENT = "#cc0000"
_CMP_COLORS = ["#e67e00", "#2ca02c", "#9467bd", "#8c564b", "#17becf"]


def register_droogte_callbacks(app):
    @app.callback(
        Output(ids.DROOGTE_CHART, "figure"),
        Output(ids.DROOGTE_STATUS, "children"),
        Input(ids.DROOGTE_REFRESH_BUTTON, "n_clicks"),
        State(ids.DROOGTE_STATION_DROPDOWN, "value"),
        State(ids.DROOGTE_REF_START, "value"),
        State(ids.DROOGTE_REF_END, "value"),
        State(ids.DROOGTE_CMP_YEARS, "value"),
        State(ids.DROOGTE_CLIP_TOGGLE, "value"),
        prevent_initial_call=True,
    )
    def update_droogte_chart(
        n_clicks,
        station_code,
        ref_start,
        ref_end,
        cmp_years,
        clip_toggle,
    ):
        if station_code is None:
            return no_update, "Selecteer een station."

        clip_negative = "clip" in (clip_toggle or [])
        ref_start = int(ref_start or 1990)
        ref_end = int(ref_end or 2020)
        cmp_years = [int(y) for y in (cmp_years or [])]

        station = STATIONS_BY_CODE.get(station_code)
        station_label = f"{station.name} ({station_code})" if station else str(station_code)

        try:
            df = fetch_knmi_daily(station_code, start_year=min(ref_start, *cmp_years, 1990) if cmp_years else ref_start)
        except Exception as exc:
            _log.exception("KNMI-data ophalen mislukt")
            return (
                {"layout": {"title": f"Fout bij ophalen KNMI-data: {exc}"}},
                f"Fout: {exc}",
            )

        if df.empty or "RH" not in df.columns or "EV24" not in df.columns:
            return (
                {"layout": {"title": "Geen data beschikbaar voor dit station."}},
                "Geen data.",
            )

        deficit = daily_deficit(df["RH"], df["EV24"])
        cum = cumulative_deficit_by_doy(deficit, clip_negative=clip_negative)
        pivot = pivot_by_doy(cum)
        ref_pivot = select_reference_years(pivot, ref_start, ref_end)

        if ref_pivot.empty:
            return (
                {"layout": {"title": f"Geen data in referentieperiode {ref_start}–{ref_end}."}},
                "Lege referentieperiode.",
            )

        bands = percentile_bands(ref_pivot)
        cur_series = current_year_series(cum)
        cmp_df = comparison_year_series(cum, cmp_years) if cmp_years else None

        fig = _build_figure(bands, cur_series, cmp_df, station_label, ref_start, ref_end)

        n_ref_years = ref_pivot.shape[1]
        status = (
            f"Station {station_label} | "
            f"Referentie {ref_start}–{ref_end} ({n_ref_years} jaar) | "
            f"Huidig jaar: {cur_series.name}"
        )
        return fig, status


import pandas as _pd


def _doy_to_date(doy_list: list[int]) -> list[str]:
    """Zet dag-van-het-jaar om naar datum-strings (jaar 2000 = schrikkeljaar)."""
    origin = _pd.Timestamp("2000-01-01")
    return [(origin + _pd.Timedelta(days=int(d) - 1)).strftime("%m-%d") for d in doy_list]


def _build_figure(
    bands,
    cur_series,
    cmp_df,
    station_label: str,
    ref_start: int,
    ref_end: int,
) -> dict:
    doy = bands.index.tolist()
    dates = _doy_to_date(doy)
    traces: list[go.BaseTraceType] = []

    # ── Percentielband p5-p95 (gearceerd) ───────────────────────────────────
    traces.append(go.Scatter(
        x=dates + dates[::-1],
        y=bands["p95"].tolist() + bands["p5"].tolist()[::-1],
        fill="toself",
        fillcolor=_COLOR_BAND_OUTER,
        line={"width": 0},
        showlegend=True,
        name=f"P5–P95 ({ref_start}–{ref_end})",
        hoverinfo="skip",
    ))

    # ── Percentielband p25-p75 (gearceerd) ──────────────────────────────────
    traces.append(go.Scatter(
        x=dates + dates[::-1],
        y=bands["p75"].tolist() + bands["p25"].tolist()[::-1],
        fill="toself",
        fillcolor=_COLOR_BAND_INNER,
        line={"width": 0},
        showlegend=True,
        name=f"P25–P75 ({ref_start}–{ref_end})",
        hoverinfo="skip",
    ))

    # ── Mediaan ─────────────────────────────────────────────────────────────
    traces.append(go.Scatter(
        x=dates,
        y=bands["p50"].tolist(),
        mode="lines",
        line={"color": _COLOR_MEDIAN, "width": 1.5, "dash": "dot"},
        name=f"Mediaan ({ref_start}–{ref_end})",
    ))

    # ── Vergelijkingsjaren ───────────────────────────────────────────────────
    if cmp_df is not None and not cmp_df.empty:
        for i, yr in enumerate(cmp_df.columns):
            s = cmp_df[yr].dropna()
            traces.append(go.Scatter(
                x=_doy_to_date(s.index.tolist()),
                y=s.values.tolist(),
                mode="lines",
                line={"color": _CMP_COLORS[i % len(_CMP_COLORS)], "width": 1.5},
                name=str(yr),
            ))

    # ── Huidig jaar (dik, rood) ──────────────────────────────────────────────
    s = cur_series.dropna()
    traces.append(go.Scatter(
        x=_doy_to_date(s.index.tolist()),
        y=s.values.tolist(),
        mode="lines",
        line={"color": _COLOR_CURRENT, "width": 3},
        name=f"{cur_series.name} (huidig)",
    ))

    layout = {
        "title": f"Cumulatief neerslagtekort — {station_label}",
        "xaxis": {
            "title": "",
            "type": "category",
            "tickvals": _doy_to_date([1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]),
            "ticktext": ["jan", "feb", "mrt", "apr", "mei", "jun",
                         "jul", "aug", "sep", "okt", "nov", "dec"],
            "showgrid": True,
            "gridcolor": "#f0f0f0",
        },
        "yaxis": {
            "title": "Cumulatief tekort (mm)",
            "showgrid": True,
            "gridcolor": "#f0f0f0",
            "zeroline": True,
            "zerolinecolor": "#888",
            "zerolinewidth": 1,
        },
        "legend": {
            "orientation": "h",
            "xanchor": "left",
            "yanchor": "bottom",
            "x": 0.0,
            "y": 1.02,
        },
        "dragmode": "pan",
        "margin": {"t": 60, "b": 40},
        "hovermode": "x unified",
    }
    return {"data": traces, "layout": layout}
