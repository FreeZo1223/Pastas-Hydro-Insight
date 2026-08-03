import base64
import logging
import zipfile
from pathlib import Path

import dash_bootstrap_components as dbc
import pastastore as pst
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from pastasdash.application.components.shared import ids, tabcontainer
from pastasdash.application.droogte import tab as tab_droogte
from pastasdash.application.settings import settings
from pastasdash.application.utils import temporary_file

_log = logging.getLogger(__name__)


def _looks_like_bro_loket_zip(zip_path: str) -> bool:
    """Detecteer of een ZIP een BRO Loket-export is (i.p.v. PastaStore-ZIP)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return any(
                "BRO_Grondwatermonitoringput" in n and n.endswith(".xml")
                for n in zf.namelist()
            )
    except Exception:  # noqa: BLE001
        return False


def _looks_like_bro_loket_dir(folder_path: str) -> bool:
    """Detecteer of een map een uitgepakte BRO Loket-export is."""
    try:
        return any(Path(folder_path).rglob("GMW*.xml"))
    except Exception:  # noqa: BLE001
        return False


def _load_pastastore_smart(path: str) -> "pst.PastaStore":
    """Laad een PastaStore uit een ZIP, BRO Loket-ZIP of BRO Loket-map.

    Accepteert:
    - Native PastaStore-ZIP (``.pastastore`` of ``.zip``)
    - BRO Loket export-ZIP (bevat GMW XML's)
    - Uitgepakte BRO Loket-map (mappad opgegeven via tekstinvoer)

    Bij BRO Loket-formaat wordt automatisch een KNMI-fetch gedaan voor
    het dichtstbijzijnde klimaatstation.
    """
    try:
        from lesa_agent.bro_loket_cli import bro_loket_zip_to_pastastore
        _have_lesa = True
    except ImportError:
        _have_lesa = False

    p = Path(path)
    if p.is_dir():
        _log.info("BRO Loket-map gedetecteerd; auto-conversie naar PastaStore...")
        if not _have_lesa:
            raise RuntimeError(
                "Detected BRO Loket map but lesa_agent is not installed; "
                "use 'lesa-bro-to-pastastore' CLI eerst."
            )
        return bro_loket_zip_to_pastastore(path, verbose=False)

    if _looks_like_bro_loket_zip(path):
        _log.info("BRO Loket-ZIP gedetecteerd; auto-conversie naar PastaStore...")
        if not _have_lesa:
            raise RuntimeError(
                "Detected BRO Loket ZIP but lesa_agent is not installed; "
                "use 'lesa-bro-to-pastastore' CLI eerst."
            )
        return bro_loket_zip_to_pastastore(path, verbose=False)

    return pst.PastaStore.from_zip(path)


def register_general_callbacks(app, pstore):
    @app.callback(
        Output(ids.HELP_MODAL, "is_open"),
        Input(ids.HELP_BUTTON_OPEN, "n_clicks"),
        Input(ids.HELP_BUTTON_CLOSE, "n_clicks"),
        State(ids.HELP_MODAL, "is_open"),
    )
    def toggle_modal(n1, n2, is_open):
        """Toggle help modal window.

        Parameters
        ----------
        n1 : int
            button open help n_clicks
        n2 : int
            button close help n_clicks
        is_open : bool
            remember state of modal

        Returns
        -------
        bool
            whether window is open or closed
        """
        if n1 or n2:
            return not is_open
        return is_open

    @app.callback(
        Output(ids.TAB_CONTENT, "children"),
        Output(ids.ALERT_TAB_RENDER, "data"),
        Output(ids.LOAD_PASTASTORE_BUTTON, "contents"),
        Input(ids.TAB_CONTAINER, "value"),
        Input(ids.LOAD_PASTASTORE_BUTTON, "contents"),
        Input(ids.BRO_FOLDER_BUTTON, "n_clicks"),
        State(ids.SELECTED_OSERIES_STORE, "data"),
        State(ids.BRO_FOLDER_INPUT, "value"),
        # prevent_initial_call=True,
    )
    def render_tab_content(tab, pastastore_config, folder_n_clicks, selected_data=None, folder_path=None):
        """Render tab content.

        Parameters
        ----------
        tab : str
            selected tab
        selected_data : str or list of str, or None
            selected data points in overview tab

        Returns
        -------
        tuple
            tuple containing tab content and alert data
        """
        empty_alert = (
            False,  # show alert
            "success",  # alert color
            "",  # empty alert message
        )
        # Load pastastore from .pastastore config file or BRO folder path
        reset_config_file_store = None
        if ctx.triggered_id == ids.BRO_FOLDER_BUTTON and folder_n_clicks:
            if not folder_path or not folder_path.strip():
                return (
                    no_update,
                    (True, "danger", "Voer een mappad in."),
                    reset_config_file_store,
                )
            p = Path(folder_path.strip())
            if not p.is_dir():
                return (
                    no_update,
                    (True, "danger", f"Map niet gevonden: {folder_path}"),
                    reset_config_file_store,
                )
            if not _looks_like_bro_loket_dir(str(p)):
                return (
                    no_update,
                    (True, "danger", f"Geen BRO Loket-mapstructuur gevonden in: {folder_path}"),
                    reset_config_file_store,
                )
            try:
                pastastore = _load_pastastore_smart(str(p))
                pstore.set_pastastore(pastastore)
            except Exception as e:  # noqa: BLE001
                return (
                    no_update,
                    (True, "danger", str(e)),
                    reset_config_file_store,
                )
        elif pastastore_config is not None:
            content_type, content_string = pastastore_config.split(",")
            decoded = base64.b64decode(content_string)
            if "zip" in content_type:
                with temporary_file(decoded) as f:
                    pastastore = _load_pastastore_smart(f)
                if settings["PARALLEL"]:
                    raise ValueError(
                        "Parallel processing is not supported for DictConnector files. "
                        "Please modify the PastasDash config file and set "
                        "`PARALLEL: false`."
                    )
            else:
                with temporary_file(decoded) as f:
                    pastastore = pst.PastaStore.from_pastastore_config_file(f)
            try:
                pstore.set_pastastore(pastastore)
            except ValueError as e:
                return (
                    no_update,
                    (
                        True,  # show alert
                        "danger",  # alert color
                        str(e),  # alert message
                    ),
                    reset_config_file_store,
                )
        # render tab content
        if tab == ids.TAB_OVERVIEW:
            if (
                selected_data is not None
                and len(selected_data) > settings["SERIES_LOAD_LIMIT"]
            ):
                selected_data = None
            return (
                tabcontainer.tab_overview.render_content(pstore, selected_data),
                empty_alert,
                reset_config_file_store,
            )
        elif tab == ids.TAB_MODEL:
            if (
                selected_data is not None
                and len(selected_data) > settings["SERIES_LOAD_LIMIT"]
            ):
                alert = (
                    True,  # show alert
                    "warning",  # alert color
                    (
                        "Multiple time series selected in overview tab, "
                        "use dropdown to select time series, or select a single "
                        "time series in Overview tab."
                    ),  # alert message
                )
            else:
                alert = empty_alert

            return (
                tabcontainer.tab_model.render_content(pstore, selected_data),
                alert,
                reset_config_file_store,
            )
        elif tab == ids.TAB_MAPS:
            return (
                tabcontainer.tab_maps.render_content(pstore),
                empty_alert,
                reset_config_file_store,
            )
        elif tab == ids.TAB_COMPARE:
            return (
                tabcontainer.tab_compare.render_content(pstore, selected_data),
                empty_alert,
                reset_config_file_store,
            )
        elif tab == ids.TAB_DROOGTE:
            return (
                tab_droogte.render_content(),
                empty_alert,
                reset_config_file_store,
            )
        else:
            raise PreventUpdate

    @app.callback(
        Output(ids.ALERT_DIV, "children"),
        Input(ids.ALERT_TAB_RENDER, "data"),
        Input(ids.ALERT_TIME_SERIES_CHART, "data"),
        Input(ids.ALERT_PLOT_MODEL_RESULTS, "data"),
        prevent_initial_call=True,
    )
    def show_alert(*args, **kwargs):
        """Show alert message.

        Parameters
        ----------
        *args
            alert data
        **kwargs
            callback context
        """
        if len(kwargs) > 0:
            ctx_ = kwargs["callback_context"]
            triggered_id = ctx_.triggered[0]["prop_id"].split(".")[0]
            inputs_list = ctx_.inputs_list
        else:
            triggered_id = ctx.triggered_id
            inputs_list = ctx.inputs_list

        if any(args):
            for i in range(len(inputs_list)):
                if inputs_list[i]["id"] == triggered_id:
                    break
            alert_data = args[i]
            is_open, color, message = alert_data
        else:
            raise PreventUpdate
        return [
            dbc.Alert(
                children=[
                    html.P(message, id=ids.ALERT_BODY),
                ],
                id=ids.ALERT,
                color=color,
                dismissable=True,
                duration=5000,
                fade=True,
                is_open=is_open,
            ),
        ]

    # @app.callback(
    #     Output(ids.PASTASTORE_CONFIG_FILE_STORE, "data", allow_duplicate=True),
    #     Input(ids.LOAD_PASTASTORE_BUTTON, "contents"),
    #     prevent_initial_call=True,
    # )
    # def load_pastastore(contents):
    #     """Store pastastore config file.

    #     Parameters
    #     ----------
    #     contents : tuple
    #         contents from upload component

    #     Returns
    #     -------
    #     str
    #         64bit encoded content string
    #     """
    #     if contents is not None:
    #         return contents
