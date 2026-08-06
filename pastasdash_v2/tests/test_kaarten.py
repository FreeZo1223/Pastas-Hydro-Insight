"""Regressietests voor de kaartfiguren.

Aanleiding: plotly 6 verwijderde ``Scattermapbox`` (vervangen door
``Scattermap`` op MapLibre). Dat brak de kaarten pas zichtbaar toen er een
verse omgeving werd opgezet — precies wat een collega bij een eerste
installatie overkomt. Deze tests bouwen de figuren echt op, zodat zo'n breuk
in de testsuite valt en niet in het gezicht van de gebruiker.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from pastasdash_v2.ui.components.plots import map_oseries, map_trace_cls


@pytest.fixture
def peilbuizen() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lat": [51.48, 52.10],
            "lon": [3.44, 5.12],
            "n_observations": [230, 180],
        },
        index=["B42C0133001", "B42C0133002"],
    )


@pytest.mark.unit
class TestKaartTrace:
    def test_kiest_bestaande_trace(self):
        trace_cls, sleutel = map_trace_cls()
        assert hasattr(go, trace_cls.__name__)
        assert sleutel in {"map", "mapbox"}

    def test_sleutel_past_bij_trace(self):
        """map_* hoort bij Scattermap, mapbox_* bij Scattermapbox."""
        trace_cls, sleutel = map_trace_cls()
        verwacht = "map" if trace_cls.__name__ == "Scattermap" else "mapbox"
        assert sleutel == verwacht


@pytest.mark.unit
class TestPeilbuiskaart:
    def test_bouwt_figuur_met_beide_punten(self, peilbuizen):
        fig = map_oseries(peilbuizen)
        assert len(fig.data) == 1
        assert len(fig.data[0].lat) == 2

    def test_layout_gebruikt_geldige_sleutels(self, peilbuizen):
        """Een verkeerd voorvoegsel geeft geen fout maar wél een blinde kaart."""
        _, sleutel = map_trace_cls()
        fig = map_oseries(peilbuizen)
        assert fig.layout[sleutel].style == "open-street-map"
        assert fig.layout[sleutel].zoom == 8

    def test_selectie_krijgt_afwijkende_opmaak(self, peilbuizen):
        fig = map_oseries(peilbuizen, selected=["B42C0133001"])
        kleuren = list(fig.data[0].marker.color)
        groottes = list(fig.data[0].marker.size)
        assert kleuren[0] != kleuren[1], "Selectie moet een eigen kleur krijgen."
        assert groottes[0] > groottes[1], "Selectie moet groter zijn."

    def test_zonder_locaties_een_nette_melding(self):
        leeg = pd.DataFrame({"lat": [None], "lon": [None]}, index=["X"])
        fig = map_oseries(leeg)
        assert fig.layout.annotations, "Verwacht een uitleg in plaats van een lege kaart."
