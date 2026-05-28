"""Plotly-figuur factories (puur, geen UI-binding)."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pastasdash_v2.config import BRAND_COLOR

log = logging.getLogger(__name__)


def empty_figure(message: str = "Geen data") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=14, color="#888")
    )
    fig.update_layout(
        template="plotly_white", margin=dict(l=20, r=20, t=30, b=30), height=420
    )
    return fig


def timeseries_overlay(
    series: dict[str, pd.Series], title: str = "Tijdreeksen", height: int = 480
) -> go.Figure:
    """Meerdere reeksen in één plot."""
    fig = go.Figure()
    for name, s in series.items():
        if s is None or s.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=s.index, y=s.values, mode="lines+markers",
                name=name, marker=dict(size=3), line=dict(width=1.2),
            )
        )
    fig.update_layout(
        title=title, template="plotly_white",
        margin=dict(l=20, r=20, t=40, b=30), height=height,
        legend=dict(orientation="h", y=-0.15), hovermode="x unified",
    )
    fig.update_yaxes(title_text="m NAP")
    return fig


def timeseries_stacked(
    series: dict[str, pd.Series], title: str = "Tijdreeksen (gestapeld)", height_per: int = 180
) -> go.Figure:
    items = [(n, s) for n, s in series.items() if s is not None and not s.empty]
    if not items:
        return empty_figure()
    fig = make_subplots(
        rows=len(items), cols=1, shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=[n for n, _ in items],
    )
    for i, (name, s) in enumerate(items, start=1):
        fig.add_trace(
            go.Scatter(x=s.index, y=s.values, mode="lines+markers", name=name, marker=dict(size=3)),
            row=i, col=1,
        )
        fig.update_yaxes(title_text="m NAP", row=i, col=1)
    fig.update_layout(
        title=title, template="plotly_white", height=max(320, len(items) * height_per),
        showlegend=False, margin=dict(l=20, r=20, t=50, b=30),
    )
    return fig


def map_oseries(
    df: pd.DataFrame, selected: list[str] | None = None, height: int = 520
) -> go.Figure:
    """Plotly mapbox kaart met alle oseries; selectie wordt accent-gekleurd."""
    if df.empty or "lat" not in df.columns or df["lat"].isna().all():
        return empty_figure("Geen locatiegegevens beschikbaar")

    selected = set(selected or [])
    colors = [BRAND_COLOR if n not in selected else "#f7a31c" for n in df.index]
    sizes = [12 if n in selected else 8 for n in df.index]

    fig = go.Figure()
    fig.add_trace(
        go.Scattermapbox(
            lat=df["lat"], lon=df["lon"],
            text=df.index, mode="markers",
            marker=dict(size=sizes, color=colors),
            hovertemplate="<b>%{text}</b><br>lat=%{lat:.4f}<br>lon=%{lon:.4f}<extra></extra>",
        )
    )
    center_lat = float(df["lat"].mean())
    center_lon = float(df["lon"].mean())
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_center=dict(lat=center_lat, lon=center_lon),
        mapbox_zoom=8,
        margin=dict(l=0, r=0, t=0, b=0), height=height,
        clickmode="event+select",
    )
    return fig


def model_results_figure(ml) -> go.Figure:
    """PASTAS-model results plot via de officiële plotly extension."""
    try:
        from pastas.extensions import register_plotly

        register_plotly()
        return ml.plotly.results()
    except Exception as exc:  # noqa: BLE001
        log.warning("Pastas plotly extension faalde: %s; val terug.", exc)
        s_obs = ml.observations()
        s_sim = ml.simulate()
        return timeseries_overlay({"obs": s_obs, "sim": s_sim}, title=f"Model: {ml.name}")


def model_diagnostics_figure(ml) -> go.Figure:
    try:
        from pastas.extensions import register_plotly

        register_plotly()
        return ml.plotly.diagnostics()
    except Exception:  # noqa: BLE001
        return empty_figure("Diagnostics niet beschikbaar")


def droogte_figure(
    bands: pd.DataFrame,
    current: pd.Series,
    comparisons: pd.DataFrame | None = None,
    title: str = "Cumulatief neerslagtekort",
) -> go.Figure:
    """Plot percentielbanden + huidig jaar + vergelijkingsjaren tegen DOY."""
    fig = go.Figure()

    # banden p5-p95 en p25-p75
    if {"p5", "p95"}.issubset(bands.columns):
        fig.add_trace(
            go.Scatter(
                x=bands.index, y=bands["p95"], mode="lines",
                line=dict(width=0), showlegend=False, hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=bands.index, y=bands["p5"], mode="lines", fill="tonexty",
                line=dict(width=0), fillcolor="rgba(200,200,200,0.4)", name="p5–p95",
            )
        )
    if {"p25", "p75"}.issubset(bands.columns):
        fig.add_trace(
            go.Scatter(
                x=bands.index, y=bands["p75"], mode="lines", line=dict(width=0),
                showlegend=False, hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=bands.index, y=bands["p25"], mode="lines", fill="tonexty",
                line=dict(width=0), fillcolor="rgba(150,150,150,0.55)", name="p25–p75",
            )
        )
    if "p50" in bands.columns:
        fig.add_trace(
            go.Scatter(x=bands.index, y=bands["p50"], mode="lines",
                       line=dict(color="black", dash="dot", width=1.5), name="mediaan")
        )

    if comparisons is not None:
        for col in comparisons.columns:
            fig.add_trace(
                go.Scatter(x=comparisons.index, y=comparisons[col].values,
                           mode="lines", line=dict(width=1.3), name=str(col), opacity=0.85)
            )

    if current is not None and not current.empty:
        fig.add_trace(
            go.Scatter(x=current.index, y=current.values, mode="lines",
                       line=dict(color=BRAND_COLOR, width=2.5), name=current.name)
        )

    fig.update_layout(
        title=title, template="plotly_white", height=520,
        margin=dict(l=20, r=20, t=40, b=30),
        xaxis=dict(
            title="Maand",
            tickmode="array",
            tickvals=[1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335],
            ticktext=["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"],
        ),
        yaxis=dict(title="Cumulatief tekort (mm)"),
        legend=dict(orientation="h", y=-0.18),
        hovermode="x unified",
    )
    return fig
