import numpy as np
import pandas as pd
from dash import Input, Output, Patch, State, no_update

from pastasdash.application.components.overview.chart import plot_timeseries
from pastasdash.application.components.shared import ids
from pastasdash.application.settings import settings


def register_overview_callbacks(app, pstore):
    @app.callback(
        Output(ids.SELECTED_OSERIES_STORE, "data"),
        Input(ids.OVERVIEW_MAP, "selectedData"),
        State(ids.SELECTED_OSERIES_STORE, "data"),
    )
    def store_modeldetails_dropdown_value(selected_data, current_value):
        """Store model results tab dropdown value.

        Parameters
        ----------
        selected_data : list of dict
            selected data points from map
        current_value : str
            current selected value

        Returns
        -------
        names : list of str
            list of selected names
        """
        if selected_data is not None:
            pts = pd.DataFrame(selected_data["points"])
            if not pts.empty:
                names = pts["text"].tolist()
                return names
            else:
                return None if current_value is None else current_value
        else:
            return None if current_value is None else current_value

    @app.callback(
        Output(ids.SERIES_CHART, "figure"),
        Output(ids.OVERVIEW_TABLE, "data"),
        Output(ids.ALERT_TIME_SERIES_CHART, "data"),
        Output(ids.OVERVIEW_TABLE_SELECTION_1, "data"),
        Input(ids.OVERVIEW_MAP, "selectedData"),
        Input(ids.OVERVIEW_TABLE, "selected_row_ids"),
        Input(ids.OVERVIEW_LAYOUT_MODE, "value"),
        Input(ids.OVERVIEW_STRESS_CHECKLIST, "value"),
        State(ids.SELECTED_OSERIES_STORE, "data"),
        State(ids.OVERVIEW_TABLE_SELECTION_1, "data"),
        State(ids.OVERVIEW_TABLE_SELECTION_2, "data"),
        background=settings["BACKGROUND_CALLBACKS"],
        running=[
            (Output(ids.OVERVIEW_CANCEL_BUTTON, "disabled"), False, True),
        ],
        cancel=[Input(ids.OVERVIEW_CANCEL_BUTTON, "n_clicks")],
        prevent_initial_call=True,
    )
    def plot_overview_time_series(
        map_selection,
        table_selected_row_ids,
        layout_mode,
        show_stresses,
        current_selected_oseries,
        table_selected_1,
        table_selected_2,
    ):
        """Plots an overview time series based on selected data.

        Parameters
        ----------
        map_selection : dict
            Dictionary containing data points selected by the user on the map.
        current_selected_oseries : list
            Current list of selected observation series.
        table_selected_1 : tuple or None
            Tuple containing the date and table data for the first table selection.
        table_selected_2 : tuple or None
            Tuple containing the date and table data for the second table selection.

        Returns
        -------
        chart : dict
            Dictionary representing the chart layout and data.
        table : list
            List of records representing the table data.
        alert : tuple
            Tuple containing a boolean indicating whether to show an alert, the alert
            type, and the alert message.
        timestamp : tuple
            Tuple containing the current timestamp and a boolean indicating the status.
        """
        usecols = [
            "id",
            pstore.column_mapping["x"],
            pstore.column_mapping["y"],
            pstore.column_mapping["screen_top"],
            pstore.column_mapping["screen_bottom"],
        ]

        # Combineer selecties uit kaart + tabel-checkboxes (union)
        names: list[str] = []
        if map_selection is not None:
            pts = pd.DataFrame(map_selection.get("points", []))
            if not pts.empty and "text" in pts.columns:
                names.extend(pts["text"].tolist())
        if table_selected_row_ids:
            # row_ids zijn integer-posities (zie datasource.py: oseries['id'] = arange)
            # Map naar oseries-namen via de id-kolom
            table_names = pstore.oseries.loc[
                pstore.oseries["id"].isin(table_selected_row_ids)
            ].index.tolist()
            names.extend(table_names)
        # Dedup, keep order
        seen: set[str] = set()
        names = [n for n in names if not (n in seen or seen.add(n))]
        if not names:
            names = current_selected_oseries or None

        # Limit-check
        if names is not None and len(names) > settings["SERIES_LOAD_LIMIT"]:
            return (
                no_update,
                no_update,
                (
                    True, "warning",
                    f"Te veel geselecteerde peilbuizen! Max {settings['SERIES_LOAD_LIMIT']}.",
                ),
                (pd.Timestamp.now().isoformat(), False),
            )

        table = pstore.oseries.loc[:, usecols].reset_index().to_dict("records")

        if names is None:
            return (
                {"layout": {"title": "Geen peilbuizen geselecteerd. Lasso/klik op de "
                                    "kaart, of vink rijen aan in de tabel."}},
                table,
                (False, None, None),
                (pd.Timestamp.now().isoformat(), False),
            )

        try:
            chart = plot_timeseries(
                pstore, names,
                layout_mode=layout_mode or "overlay",
                show_stresses=show_stresses or [],
            )
            if chart is None:
                return (
                    {"layout": {"title": "Geen data in geselecteerde reeksen."}},
                    table,
                    (True, "warning", f"Geen data voor: {names}."),
                    (pd.Timestamp.now().isoformat(), False),
                )
            return (
                chart, table,
                (False, None, None),
                (pd.Timestamp.now().isoformat(), False),
            )
        except Exception as e:
            return (
                {"layout": {"title": "Fout bij plotten."}},
                table,
                (True, "danger", f"Error! {e}"),
                (pd.Timestamp.now().isoformat(), False),
            )

    @app.callback(
        Output(ids.OVERVIEW_MAP, "selectedData"),
        Output(ids.OVERVIEW_MAP, "figure"),
        Output(ids.OVERVIEW_TABLE_SELECTION_2, "data"),
        Input(ids.OVERVIEW_TABLE, "selected_cells"),
        State(ids.OVERVIEW_TABLE, "derived_virtual_data"),
        prevent_initial_call=True,
    )
    def highlight_point_on_map_from_table(table_selection, table):
        """Highlights points on a map based on selected cells from overview table.

        Parameters
        ----------
        selected_cells : list of dict or None
            List of dictionaries containing information about selected cells.
            Each dictionary should have a "row" key. If None, the function returns
            no updates.
        table : dict
            records representing the table data.

        Returns
        -------
        tuple
            A tuple containing:
            - dict: A dictionary with information about the highlighted points.
            - Patch: An object representing the updated map patch with selected points.
            - tuple: A tuple containing the current timestamp and a boolean indicating
              if the update was successful.
        """
        if table_selection is None:
            return no_update, no_update, (pd.Timestamp.now().isoformat(), False)

        rows = np.unique([cell["row_id"] for cell in table_selection]).tolist()
        df = pd.DataFrame.from_dict(table, orient="columns").set_index("id")
        loc = df.loc[rows]
        pts = loc.index.tolist()

        dfm = (
            pstore.oseries.reset_index(drop=("name" in pstore.oseries.columns))
            .set_index("id")
            .loc[pts]
        )
        dfm["curveNumber"] = 0
        # update selected points
        mappatch = Patch()
        mappatch["data"][0]["selectedpoints"] = dfm.index.tolist()

        selectedData = {
            "points": [
                {
                    "curveNumber": dfm.at[i, "curveNumber"],
                    "pointNumber": i,
                    "pointIndex": i,
                    "lon": dfm.at[i, "lon"],
                    "lat": dfm.at[i, "lat"],
                    "text": dfm.at[i, "name"],
                }
                for i in pts
            ]
        }
        return (
            selectedData,
            mappatch,
            (pd.Timestamp.now().isoformat(), True),
        )
