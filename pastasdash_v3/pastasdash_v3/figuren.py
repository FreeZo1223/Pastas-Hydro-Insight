"""Figuren die in v2 in de NiceGUI-pagina's zelf staan.

De meeste figuren komen uit ``pastasdash_v2.ui.components.plots``. De
vergelijking van modellen en de waarden voor de resultaatkaart zijn in v2 in
de pagina's gemaakt (``ui/pages/compare.py`` en ``maps.py``); die modules
laden NiceGUI en kunnen dus niet mee naar de browser. Hier staat hetzelfde
nog eens.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import gxg, model_summary
from pastasdash_v2.ui.components.plots import empty_figure

log = logging.getLogger(__name__)

METRIEKEN = {
    "rsq": "R² (modelkwaliteit)",
    "evp": "EVP (modelkwaliteit)",
    "ghg": "GHG",
    "glg": "GLG",
    "gvg": "GVG",
    "n_observations": "Aantal metingen",
}


def vergelijk_figuur(namen: list[str]) -> go.Figure:
    """Metingen en simulatie van meerdere modellen in één grafiek."""
    fig = go.Figure()
    for naam in namen:
        try:
            ml = STORE.pstore.get_models(naam)
            obs, sim = ml.observations(), ml.simulate()
            fig.add_trace(
                go.Scatter(x=obs.index, y=obs.values, name=f"{naam} meting", mode="markers", marker=dict(size=3))
            )
            fig.add_trace(go.Scatter(x=sim.index, y=sim.values, name=f"{naam} model", mode="lines"))
        except Exception as fout:  # noqa: BLE001
            log.warning("Model %s niet te tekenen: %s", naam, fout)
    if not fig.data:
        return empty_figure("Geen van de gekozen peilbuizen heeft een model.")
    fig.update_layout(
        template="plotly_white",
        height=520,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=30, b=30),
        legend=dict(orientation="h", y=-0.15),
        yaxis_title="m NAP",
    )
    return fig


def vergelijk_tabel(namen: list[str]) -> list[dict]:
    rijen = []
    for naam in namen:
        s = model_summary(STORE.store_key, naam)
        if s:
            rijen.append({"naam": naam, **s})
    return rijen


def metriek_per_put(metriek: str) -> pd.DataFrame:
    """De oseries-tabel met een kolom ``metric_value`` voor de gekozen maat."""
    df = STORE.oseries().copy()
    if df.empty:
        return df
    modellen = set(STORE.model_names())
    waarden = []
    for naam in df.index:
        waarde = np.nan
        try:
            if metriek in ("rsq", "evp"):
                if naam in modellen:
                    waarde = float(model_summary(STORE.store_key, naam).get(metriek, np.nan))
            elif metriek in ("ghg", "glg", "gvg"):
                waarde = float(gxg(STORE.store_key, naam).get(metriek.upper(), np.nan))
            elif metriek == "n_observations":
                waarde = float(df.loc[naam].get("n_observations", np.nan))
        except Exception:  # noqa: BLE001
            waarde = np.nan
        waarden.append(waarde)
    df["metric_value"] = waarden
    return df


def punten(metriek: str | None = None) -> list[dict]:
    """Ligging van de putten, met de waarde van de gekozen maat als die gevraagd is.

    De pagina tekent hiermee zelf de kaart. De kaartfiguren van Plotly tonen
    hun punten niet in een pagina die als los bestand is geopend.
    """
    df = metriek_per_put(metriek) if metriek else STORE.oseries()
    if df.empty:
        return []
    uit = []
    for naam, rij in df.iterrows():
        if pd.isna(rij.get("lat")) or pd.isna(rij.get("lon")):
            continue
        waarde = rij.get("metric_value") if metriek else None
        uit.append(
            {
                "naam": naam,
                "lat": float(rij["lat"]),
                "lon": float(rij["lon"]),
                "waarde": None if waarde is None or pd.isna(waarde) else float(waarde),
            }
        )
    return uit
