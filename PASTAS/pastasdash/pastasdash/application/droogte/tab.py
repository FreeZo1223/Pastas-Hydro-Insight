"""Dash-layout voor het Droogte-tabblad.

Structuur:
    Sidebar (links, 3 kolommen)  |  Grafiek (rechts, 9 kolommen)

Sidebar bevat:
    - Station keuze (radio of dropdown)
    - Referentieperiode (jaar-van / jaar-tot)
    - Vergelijkingsjaren (multi-select)
    - Knip negatief (toggle)
    - Vernieuwen-knop
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from pastasdash.application.components.shared import ids
from pastasdash.application.droogte.stations import (
    DEFAULT_STATION_CODE,
    station_options,
)


_CURRENT_YEAR = __import__("datetime").date.today().year
_DEFAULT_REF_START = 1990
_DEFAULT_REF_END = 2020
_DEFAULT_CMP_YEARS = [2018, 2020, 2024]


def render() -> dcc.Tab:
    """Geeft het Tab-component terug (header only, geen content)."""
    return dcc.Tab(
        label="Droogte",
        value=ids.TAB_DROOGTE,
        className="custom-tab",
        selected_className="custom-tab--selected",
    )


def render_content() -> dbc.Container:
    """Rendert de volledige inhoud van het Droogte-tabblad."""
    return dbc.Container(
        [
            dbc.Row(
                [
                    # ── Sidebar ──────────────────────────────────────────────
                    dbc.Col(
                        _render_sidebar(),
                        width=3,
                        style={"borderRight": "1px solid #dee2e6", "paddingRight": 16},
                    ),
                    # ── Grafiek ──────────────────────────────────────────────
                    dbc.Col(
                        [
                            dcc.Loading(
                                id=ids.DROOGTE_LOADING,
                                type="dot",
                                children=[
                                    dcc.Graph(
                                        id=ids.DROOGTE_CHART,
                                        config={"displayModeBar": True, "scrollZoom": True},
                                        style={"height": "75vh"},
                                        figure={"layout": {"title": "Selecteer een station en klik Vernieuwen"}},
                                    ),
                                ],
                            ),
                            html.Div(id=ids.DROOGTE_STATUS, style={"fontSize": 11, "color": "#888", "marginTop": 4}),
                        ],
                        width=9,
                    ),
                ],
                style={"marginTop": 12},
            ),
        ],
        fluid=True,
    )


def _render_sidebar() -> html.Div:
    current_year = _CURRENT_YEAR
    return html.Div(
        [
            html.H6("Instellingen", style={"fontWeight": "bold", "marginBottom": 12}),

            # Station
            html.Label("Station", style={"fontSize": 12, "fontWeight": "bold"}),
            dcc.Dropdown(
                id=ids.DROOGTE_STATION_DROPDOWN,
                options=station_options(),
                value=DEFAULT_STATION_CODE,
                clearable=False,
                style={"fontSize": 12, "marginBottom": 12},
            ),

            # Referentieperiode
            html.Label("Referentieperiode", style={"fontSize": 12, "fontWeight": "bold"}),
            dbc.Row(
                [
                    dbc.Col(
                        dcc.Input(
                            id=ids.DROOGTE_REF_START,
                            type="number",
                            value=_DEFAULT_REF_START,
                            min=1950,
                            max=current_year - 1,
                            step=1,
                            style={"width": "100%", "fontSize": 12},
                        ),
                        width=6,
                    ),
                    dbc.Col(
                        dcc.Input(
                            id=ids.DROOGTE_REF_END,
                            type="number",
                            value=_DEFAULT_REF_END,
                            min=1951,
                            max=current_year,
                            step=1,
                            style={"width": "100%", "fontSize": 12},
                        ),
                        width=6,
                    ),
                ],
                style={"marginBottom": 12},
            ),

            # Vergelijkingsjaren
            html.Label("Vergelijkingsjaren", style={"fontSize": 12, "fontWeight": "bold"}),
            dcc.Dropdown(
                id=ids.DROOGTE_CMP_YEARS,
                options=[{"label": str(y), "value": y} for y in range(1950, current_year + 1)],
                value=_DEFAULT_CMP_YEARS,
                multi=True,
                placeholder="Selecteer jaren…",
                style={"fontSize": 12, "marginBottom": 12},
            ),

            # Clip toggle
            dbc.Checklist(
                id=ids.DROOGTE_CLIP_TOGGLE,
                options=[{"label": " Knip negatief (geen overschot)", "value": "clip"}],
                value=[],
                style={"fontSize": 12, "marginBottom": 16},
            ),

            # Vernieuwen
            dbc.Button(
                [html.I(className="fa-solid fa-rotate-right"), " Vernieuwen"],
                id=ids.DROOGTE_REFRESH_BUTTON,
                color="primary",
                size="sm",
                style={"width": "100%"},
            ),
        ]
    )
