"""Plotly-figuur factories (puur, geen UI-binding)."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pastasdash_v2.core.config import BRAND_COLOR

log = logging.getLogger(__name__)


def map_trace_cls() -> tuple[type, str]:
    """Geef de kaart-trace en het layout-voorvoegsel van de actieve plotly.

    Plotly 6 verving de Mapbox-kaarten door MapLibre: ``Scattermapbox`` werd
    ``Scattermap`` en de layoutsleutels ``mapbox_*`` werden ``map_*``. Door dit
    op één plek te bepalen werkt het dashboard op beide generaties en staat de
    versiekeuze niet verspreid door de code.
    """
    if hasattr(go, "Scattermap"):
        return go.Scattermap, "map"
    return go.Scattermapbox, "mapbox"


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
    """Kaart met alle peilbuizen; de selectie krijgt de accentkleur.

    Plotly 6 heeft de Mapbox-traces vervangen door MapLibre (``Scattermap``
    in plaats van ``Scattermapbox``, en ``map_*``- in plaats van
    ``mapbox_*``-layoutsleutels). We kiezen daarom op basis van wat de
    geïnstalleerde plotly aanbiedt, zodat zowel oudere als nieuwe versies
    werken.
    """
    if df.empty or "lat" not in df.columns or df["lat"].isna().all():
        return empty_figure("Geen locatiegegevens beschikbaar")

    selected = set(selected or [])
    colors = [BRAND_COLOR if n not in selected else "#C2703D" for n in df.index]
    sizes = [13 if n in selected else 8 for n in df.index]

    trace_cls, sleutel = map_trace_cls()

    fig = go.Figure()
    fig.add_trace(
        trace_cls(
            lat=df["lat"], lon=df["lon"],
            text=df.index, mode="markers",
            marker=dict(size=sizes, color=colors),
            hovertemplate="<b>%{text}</b><br>%{lat:.4f}, %{lon:.4f}<extra></extra>",
        )
    )
    center = dict(lat=float(df["lat"].mean()), lon=float(df["lon"].mean()))
    fig.update_layout(
        **{
            f"{sleutel}_style": "open-street-map",
            f"{sleutel}_center": center,
            f"{sleutel}_zoom": 8,
        },
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


def foe_figure(
    series_dict: dict[str, pd.Series],
    average: pd.DataFrame | None = None,
    height: int = 420,
) -> go.Figure:
    """Frequency-of-Exceedance plot. ``series_dict`` per peilbuis een Series.

    ``average``: optionele DataFrame met kolommen 'foe' en 'value' (gemiddelde curve).
    """
    from pastasdash_v2.core.statistics import frequency_of_exceedance

    fig = go.Figure()
    if not series_dict and (average is None or average.empty):
        return empty_figure("Selecteer peilbuizen voor de FOE-curve.")

    for name, s in series_dict.items():
        foe = frequency_of_exceedance(s)
        if foe.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=foe["foe"], y=foe["value"], mode="lines+markers",
                name=name, marker=dict(size=4), line=dict(width=1.2),
            )
        )
    if average is not None and not average.empty:
        fig.add_trace(
            go.Scatter(
                x=average["foe"], y=average["value"], mode="lines",
                name="gemiddelde", line=dict(color="black", dash="dash", width=2),
            )
        )
    fig.update_layout(
        title="Frequency of Exceedance",
        template="plotly_white",
        margin=dict(l=20, r=20, t=40, b=30), height=height,
        xaxis=dict(title="Frequency of Exceedence (%)", range=[0, 100]),
        yaxis=dict(title="Groundwater level (m NAP)"),
        legend=dict(orientation="h", y=-0.18), hovermode="x unified",
    )
    return fig


def regime_curve_figure(
    series_dict: dict[str, pd.Series], height: int = 360
) -> go.Figure:
    """Gemiddelde grondwaterstand per maand voor elke peilbuis."""
    from pastasdash_v2.core.statistics import regime_curve

    fig = go.Figure()
    if not series_dict:
        return empty_figure("Selecteer peilbuizen voor de regime-curve.")

    has_data = False
    for name, s in series_dict.items():
        rc = regime_curve(s, freq="month")
        if rc.empty:
            continue
        has_data = True
        fig.add_trace(
            go.Scatter(
                x=rc.index, y=rc.values, mode="lines+markers",
                name=name, marker=dict(size=6), line=dict(width=1.5),
            )
        )
    if not has_data:
        return empty_figure("Onvoldoende data voor regime-curve.")

    fig.update_layout(
        title="Regime Curve",
        template="plotly_white",
        margin=dict(l=20, r=20, t=40, b=30), height=height,
        xaxis=dict(
            title="Maand",
            tickmode="array",
            tickvals=list(range(1, 13)),
            ticktext=["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
                      "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"],
        ),
        yaxis=dict(title="Groundwater level (m NAP)"),
        legend=dict(orientation="h", y=-0.22), hovermode="x unified",
    )
    return fig


def clean_fig(fig: go.Figure) -> dict:
    """Zorgt dat de figuur 100% JSON-serialiseerbaar is (geen Timestamp- of NaN-crashes in NiceGUI)."""
    import json
    return json.loads(fig.to_json())

