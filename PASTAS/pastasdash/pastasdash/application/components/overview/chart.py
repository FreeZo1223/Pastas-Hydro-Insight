import dash_bootstrap_components as dbc
import plotly.graph_objs as go
from dash import __version__ as DASH_VERSION
from dash import dcc, html
from packaging.version import parse as parse_version
from plotly.subplots import make_subplots

from pastasdash.application.components.shared import ids


def render_cancel_button():
    """Renders a cancel button component.

    Returns
    -------
    html.Div
        A Div containing a disabled cancel button.
    """
    return html.Div(
        children=[
            dbc.Button(
                html.Span(
                    [
                        html.I(className="fa-regular fa-circle-stop"),
                        " Cancel",
                    ],
                    id="span-cancel-button",
                    n_clicks=0,
                ),
                style={
                    "margin-top": 10,
                    "margin-bottom": 10,
                },
                disabled=True,
                id=ids.OVERVIEW_CANCEL_BUTTON,
            ),
        ]
    )


def render(pstore, selected_data):
    kwargs = (
        {"delay_show": 500}
        if parse_version(DASH_VERSION) >= parse_version("2.17.0")
        else {}
    )
    return html.Div(
        id="series-chart-div",
        children=[
            _render_controls(),
            dcc.Loading(
                id=ids.LOADING_SERIES_CHART,
                type="dot",
                style={"position": "absolute", "align-self": "center"},
                parent_className="loading-wrapper",
                children=[
                    dcc.Graph(
                        figure=plot_timeseries(pstore, selected_data),
                        id=ids.SERIES_CHART,
                        config={"displayModeBar": True, "scrollZoom": True},
                        style={"height": "45vh", "margin-bottom": 0},
                    ),
                ],
                **kwargs,
            ),
        ],
        style={
            "position": "relative",
            "justify-content": "center",
            "margin-bottom": 0,
        },
    )


def _render_controls():
    """Controls boven de chart: layout-mode + stress-toggles."""
    return dbc.Row(
        [
            dbc.Col(
                [
                    html.Label(
                        "Layout:",
                        style={"marginRight": 8, "fontSize": 12, "fontWeight": "bold"},
                    ),
                    dcc.RadioItems(
                        id=ids.OVERVIEW_LAYOUT_MODE,
                        options=[
                            {"label": " Overlay (samen)", "value": "overlay"},
                            {"label": " Stacked (apart)", "value": "stacked"},
                        ],
                        value="overlay",
                        inline=True,
                        labelStyle={"marginRight": 12, "fontSize": 12},
                    ),
                ],
                width="auto",
            ),
            dbc.Col(
                [
                    html.Label(
                        "Toon:",
                        style={"marginRight": 8, "fontSize": 12, "fontWeight": "bold"},
                    ),
                    dcc.Checklist(
                        id=ids.OVERVIEW_STRESS_CHECKLIST,
                        options=[
                            {"label": " Neerslag", "value": "prec"},
                            {"label": " Verdamping", "value": "evap"},
                        ],
                        value=[],
                        inline=True,
                        labelStyle={"marginRight": 12, "fontSize": 12},
                    ),
                ],
                width="auto",
            ),
        ],
        style={"marginTop": 4, "marginBottom": 2, "paddingLeft": 8},
        align="center",
    )


def plot_timeseries(pstore, names, layout_mode="overlay", show_stresses=None):
    """Plots observation data for given names.

    Parameters
    ----------
    pstore : PastaStoreInterface
        pastastore interface
    names : list of str
        List of strings of observation timeseries
    layout_mode : {"overlay", "stacked"}
        ``overlay`` plot all series in one chart (default upstream behavior).
        ``stacked`` plot each series in its own subplot row, shared x-axis.
    show_stresses : list of str or None
        Optionele subset van ``{"prec", "evap"}``. Toont KNMI-neerslag of
        Makkink-verdamping als overlay-trace (rechter y-as bij overlay,
        eigen onderste rij bij stacked).
    """
    if names is None:
        return {"layout": {"title": "No time series selected"}}

    show_stresses = list(show_stresses or [])
    stress_traces = _collect_stress_traces(pstore, show_stresses)

    no_data = []
    series_traces: list[tuple[str, go.Scattergl]] = []
    for name in names:
        ts = pstore.get_oseries(name)
        if ts.empty:
            no_data.append(True)
            continue
        no_data.append(False)
        line_kwargs = {"width": 1, "color": "gray"} if len(names) == 1 else {"width": 1}
        trace_i = go.Scattergl(
            x=ts.index, y=ts.values,
            mode="markers+lines",
            line=line_kwargs, marker={"size": 3},
            name=name, legendgroup=name, showlegend=True,
        )
        series_traces.append((name, trace_i))

    if all(no_data) and not stress_traces:
        return None

    if layout_mode == "stacked" and len(series_traces) > 1:
        return _build_stacked_figure(series_traces, stress_traces)
    return _build_overlay_figure(series_traces, stress_traces)


def _collect_stress_traces(pstore, show_stresses):
    """Bouw stress-traces voor neerslag / verdamping uit de PastaStore."""
    if not show_stresses:
        return []
    # Stress-namen die we herkennen (matchen met onze grondwater-plugin)
    stress_map: dict[str, list[str]] = {
        "prec": ["neerslag_KNMI", "neerslag", "prec", "RH", "RD"],
        "evap": ["verdamping_KNMI", "verdamping", "evap", "EV24"],
    }
    color_map = {"prec": "#3366cc", "evap": "#dd8800"}
    label_map = {"prec": "Neerslag (mm/d)", "evap": "Verdamping (mm/d)"}
    available = set(pstore.stresses.index.tolist()) if hasattr(pstore, "stresses") else set()
    traces: list[tuple[str, go.Scattergl]] = []
    for kind in show_stresses:
        candidates = stress_map.get(kind, [])
        match = next((c for c in candidates if c in available), None)
        if not match:
            continue
        try:
            s = pstore.get_stress(match)
        except Exception:
            continue
        if s is None or s.empty:
            continue
        trace = go.Scattergl(
            x=s.index, y=s.values,
            mode="lines",
            line={"width": 1, "color": color_map[kind]},
            name=label_map[kind],
            opacity=0.6,
            yaxis="y2",
        )
        traces.append((kind, trace))
    return traces


def _build_overlay_figure(series_traces, stress_traces):
    """Alle peilbuizen in één plot; stresses op rechter y-as."""
    data = [t for _, t in series_traces] + [t for _, t in stress_traces]
    layout: dict = {
        "yaxis": {"title": "Stand (m NAP)"},
        "legend": {
            "traceorder": "reversed+grouped",
            "orientation": "h",
            "xanchor": "left", "yanchor": "bottom",
            "x": 0.0, "y": 1.02,
        },
        "dragmode": "pan",
        "margin": {"t": 30, "b": 30},
    }
    if stress_traces:
        layout["yaxis2"] = {
            "title": "Neerslag / Verdamping (mm/d)",
            "overlaying": "y", "side": "right", "showgrid": False,
        }
    return {"data": data, "layout": layout}


def _build_stacked_figure(series_traces, stress_traces):
    """Eén subplot per peilbuis; stresses (indien aanwezig) onderaan."""
    n_series = len(series_traces)
    n_stress = 1 if stress_traces else 0
    rows = n_series + n_stress
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.02,
        subplot_titles=[name for name, _ in series_traces]
        + (["Stresses"] if n_stress else []),
    )
    for i, (name, trace) in enumerate(series_traces, start=1):
        # Per-subplot: niet 'reversed' legendgroup, gewoon op trace-naam
        trace.update(showlegend=False)
        fig.add_trace(trace, row=i, col=1)
        fig.update_yaxes(title_text="m NAP", row=i, col=1)
    for _, trace in stress_traces:
        trace.update(yaxis=None)  # strip secondary-y-as setting
        fig.add_trace(trace, row=rows, col=1)
    if stress_traces:
        fig.update_yaxes(title_text="mm/d", row=rows, col=1)
    fig.update_layout(
        showlegend=bool(stress_traces),
        dragmode="pan",
        margin={"t": 40, "b": 30},
    )
    return fig
