"""Smoke-tests voor bodem_bro plugin — geen live BRO HTTP.

fetch_data wordt gemockt met een synthetische GeoDataFrame. analyze()
draait volledig; we verifiëren claims, hypothesen, scope en artifacts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import geopandas as gpd
import pytest
from shapely.geometry import box

from lesa.plugins._base import Plugin, PluginInputs, PluginRawData
from lesa.plugins.bodem_bro.params import BodemBroParams
from lesa.plugins.bodem_bro.plugin import BodemBroPlugin

_SIMPLE_AOI = {
    "type": "Polygon",
    "coordinates": [[
        [26100.0, 391300.0],
        [26400.0, 391300.0],
        [26400.0, 391600.0],
        [26100.0, 391600.0],
        [26100.0, 391300.0],
    ]],
}


def _make_inputs(tmp_path: Path) -> PluginInputs:
    artifact_dir = tmp_path / "data" / "bodem_bro"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return PluginInputs(
        session_id="test-session",
        project_name="Burgh-test",
        scale_level=2,
        landscape_type="duinen",
        aoi_geojson=_SIMPLE_AOI,
        artifact_dir=str(artifact_dir),
        params={"aoi_buffer_m": 200.0, "min_vlak_ha": 0.1},
    )


def _make_bodemkaart_gdf(with_veen: bool = False) -> gpd.GeoDataFrame:
    """Synthetische bodemkaart GeoDataFrame met realistische structuur."""
    geoms = [
        box(25900, 391100, 26200, 391500),  # zandgrond
        box(26200, 391100, 26600, 391500),  # vaargrond (duin)
    ]
    codes = ["Zb23" if not with_veen else "Vc30", "Zb23"]
    names = ["Duinvaaggrond" if not with_veen else "Vlierveengrond", "Duinvaaggrond"]

    return gpd.GeoDataFrame(
        {"bodemeenheid": codes, "omschrijving": names},
        geometry=geoms,
        crs="EPSG:28992",
    )


class TestBodemBroPlugin:
    def test_protocol_compliance(self):
        plugin = BodemBroPlugin()
        assert isinstance(plugin, Plugin)
        assert plugin.PLUGIN_ID == "bodem_bro"

    def test_params_schema_valid(self):
        schema = BodemBroPlugin.params_schema()
        props = schema["properties"]
        assert "aoi_buffer_m" in props
        assert "min_vlak_ha" in props

    def test_analyze_no_features_returns_empty_outputs(self, tmp_path):
        plugin = BodemBroPlugin()
        inputs = _make_inputs(tmp_path)
        raw = PluginRawData(
            files={},
            metadata={"n_features": 0, "columns": [], "source": "test"},
        )
        raw.set_frame("bodemkaart", gpd.GeoDataFrame(columns=["geometry"]))
        outputs = plugin.analyze(inputs, raw)
        assert outputs.scope.uncertainty_level == "hoog"
        assert len(outputs.claims) == 0

    def test_analyze_with_zandgrond(self, tmp_path):
        plugin = BodemBroPlugin()
        inputs = _make_inputs(tmp_path)
        gdf = _make_bodemkaart_gdf(with_veen=False)
        raw = PluginRawData(
            files={"bodemkaart_gpkg": str(tmp_path / "data" / "bodem_bro" / "bodemkaart.gpkg")},
            metadata={"n_features": len(gdf), "columns": list(gdf.columns), "source": "test"},
        )
        raw.set_frame("bodemkaart", gdf)
        outputs = plugin.analyze(inputs, raw)

        assert len(outputs.claims) >= 1
        topics = {c.topic for c in outputs.claims}
        assert "bodem" in topics
        assert len(outputs.hypotheses) == 0  # geen veen → geen hypothese
        assert outputs.scope.uncertainty_level == "middel"

    def test_analyze_with_veen_generates_hypothesis(self, tmp_path):
        plugin = BodemBroPlugin()
        inputs = _make_inputs(tmp_path)
        gdf = _make_bodemkaart_gdf(with_veen=True)
        raw = PluginRawData(
            files={},
            metadata={"n_features": len(gdf), "columns": list(gdf.columns), "source": "test"},
        )
        raw.set_frame("bodemkaart", gdf)
        outputs = plugin.analyze(inputs, raw)

        veen_claims = [c for c in outputs.claims if "veen" in c.text.lower()]
        assert len(veen_claims) >= 1

        hyps = outputs.hypotheses
        assert len(hyps) == 1
        assert hyps[0].falsifier is not None
        assert hyps[0].confidence_level == "plausibel"

    @pytest.mark.asyncio
    async def test_fetch_data_calls_bro_skill(self, tmp_path):
        plugin = BodemBroPlugin()
        inputs = _make_inputs(tmp_path)
        fake_gdf = _make_bodemkaart_gdf()

        with patch(
            "geo_stack.skills.bro.fetch_bodemkaart",
            return_value=fake_gdf,
        ):
            raw = await plugin.fetch_data(inputs)

        assert raw.metadata["n_features"] == len(fake_gdf)
        frame = raw.get_frame("bodemkaart")
        assert frame is not None
        assert len(frame) == len(fake_gdf)
