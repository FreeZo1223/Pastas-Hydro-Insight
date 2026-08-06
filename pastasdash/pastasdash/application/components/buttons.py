import dash_bootstrap_components as dbc
from dash import dcc, html

from pastasdash.application.components.shared import ids
from pastasdash.application.settings import ASSETS_PATH

# load Modal helper text from MarkDown
with open(ASSETS_PATH / "pastasdash_help.md", "r", encoding="utf-8") as f:
    help_md = dcc.Markdown("".join(f.readlines()), mathjax=True)


def render_help_button_modal():
    """Renders a help button and modal for the PastasDash application.

    This function creates a button that, when clicked, opens a modal containing
    information about the PastasDash application. The modal includes a header,
    body with help content, and a footer with developer credits and a close button.

    Returns
    -------
    dash.html.Div
        A Dash HTML Div component containing the help button and modal.
    """
    return html.Div(
        [
            dbc.Button(
                html.Span(
                    [html.I(className="fa-solid fa-circle-info"), " Help"],
                    id="span-open-help",
                    n_clicks=0,
                ),
                id=ids.HELP_BUTTON_OPEN,
                class_name="ms-auto",
            ),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle(
                            html.H3(
                                "About PastasDash",
                                id=ids.HELP_TITLE,
                            ),
                        ),
                    ),
                    dbc.ModalBody(help_md),
                    dbc.ModalFooter(
                        [
                            html.I("Developed by D.A. Brakenhoff" ", Artesia, 2024"),
                            dbc.Button(
                                "Close",
                                id=ids.HELP_BUTTON_CLOSE,
                                className="ms-auto",
                                n_clicks=0,
                            ),
                        ]
                    ),
                ],
                id=ids.HELP_MODAL,
                is_open=False,
                scrollable=True,
                size="xl",
            ),
        ]
    )


def render_load_pastastore_button():
    """Renders a button for loading a PastasStore from a file.

    Returns
    -------
    dash.html.Div
        A Dash HTML Div component containing the load PastasStore button.
    """
    return html.Div(
        id="div-load-pastastore-button",
        className="load-button-pastastore-div",
        children=[
            dcc.Upload(
                id=ids.LOAD_PASTASTORE_BUTTON,
                accept=".pastastore,.zip",
                children=[
                    html.A(
                        html.Span(
                            [
                                html.I(className="fa-solid fa-file-import"),
                                "  Load PastaStore ",
                            ],
                            style={
                                "color": "white",
                            },
                        )
                    )
                ],
                style={
                    "width": "150px",
                    "height": "37.5px",
                    "lineHeight": "35px",
                    "borderWidth": "1px",
                    "borderStyle": "solid",
                    "borderRadius": "5px",
                    "backgroundClip": "border-box",
                    "backgroundColor": "#006f92",
                    "textAlign": "center",
                    "cursor": "pointer",
                },
            ),
            dbc.Tooltip(
                "Load a PastasStore from a .pastastore or .zip file",
                target=ids.LOAD_PASTASTORE_BUTTON,
                style={"margin-bottom": 0},
                placement="left",
            ),
        ],
        style={
            "display": "inline-block",
            "margin-top": 10,
            "margin-bottom": 10,
            "margin-right": 5,
            "margin-left": "auto",
            "verticalAlign": "middle",
        },
    )


def render_bro_folder_input():
    """Renders a text input + button to load a BRO Loket folder directly by path.

    Only useful when pastasdash runs locally (path must exist on the server).

    Returns
    -------
    dash.html.Div
        A Dash HTML Div containing a path text input and load button.
    """
    return html.Div(
        id="div-bro-folder-input",
        children=[
            dcc.Input(
                id=ids.BRO_FOLDER_INPUT,
                type="text",
                placeholder="Pad naar uitgepakte BRO-map…",
                debounce=False,
                style={
                    "width": "280px",
                    "height": "37.5px",
                    "lineHeight": "35px",
                    "borderWidth": "1px",
                    "borderStyle": "solid",
                    "borderRadius": "5px 0 0 5px",
                    "padding": "0 8px",
                    "verticalAlign": "middle",
                },
            ),
            dbc.Button(
                [html.I(className="fa-solid fa-folder-open"), " Laden"],
                id=ids.BRO_FOLDER_BUTTON,
                n_clicks=0,
                style={
                    "height": "37.5px",
                    "borderRadius": "0 5px 5px 0",
                    "backgroundColor": "#006f92",
                    "border": "1px solid #006f92",
                    "verticalAlign": "middle",
                },
            ),
            dbc.Tooltip(
                "Laad een BRO Loket-exportmap rechtstreeks via mappad "
                "(werkt alleen als pastasdash lokaal draait)",
                target=ids.BRO_FOLDER_BUTTON,
                style={"margin-bottom": 0},
                placement="left",
            ),
        ],
        style={
            "display": "inline-flex",
            "alignItems": "center",
            "margin-top": 10,
            "margin-bottom": 10,
            "margin-right": 5,
            "verticalAlign": "middle",
        },
    )
