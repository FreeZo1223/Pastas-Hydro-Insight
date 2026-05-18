"""Smoke-tests voor grondwater_pastas plugin — geen live HTTP.

fetch_data wordt gemockt; analyze() draait volledig en we verifiëren dat
claims/hypothesen/scope op verschillende data-volledigheden klopt.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from lesa.plugins._base import Plugin, PluginInputs, PluginRawData
from lesa.plugins.grondwater_pastas.params import GrondwaterPastasParams
from lesa.plugins.grondwater_pastas.plugin import GrondwaterPastasPlugin

_AOI = {
    "type": "Polygon",
    "coordinates": [[
        [26100.0, 391300.0],
        [26400.0, 391300.0],
        [26400.0, 391600.0],
        [26100.0, 391600.0],
        [26100.0, 391300.0],
    ]],
}


def _make_inputs(tmp_path: Path, **overrides) -> PluginInputs:
    artifact_dir = tmp_path / "data" / "grondwater_pastas"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    params = {
        "aoi_buffer_m": 500.0,
        "tmin": "2000-01-01",
        "tmax": "2010-12-31",
    }
    params.update(overrides)
    return PluginInputs(
        session_id="test",
        project_name="Burgh-test",
        scale_level=2,
        landscape_type="duinen",
        aoi_geojson=_AOI,
        artifact_dir=str(artifact_dir),
        params=params,
    )


def _fake_pbz_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": ["GMW001", "GMW002", "GMW003"]},
        geometry=[Point(26200, 391400), Point(26350, 391500), Point(26150, 391350)],
        crs="EPSG:28992",
    )


def _fake_neerslag(periods: int = 1000) -> pd.Series:
    idx = pd.date_range("2000-01-01", periods=periods, freq="D", name="Datum")
    return pd.Series(2.0, index=idx, name="Neerslag_mm")


def _fake_verdamping(periods: int = 1000) -> pd.Series:
    idx = pd.date_range("2000-01-01", periods=periods, freq="D", name="Datum")
    return pd.Series(1.5, index=idx, name="Verdamping_mm")


class TestGrondwaterPastasPlugin:
    def test_protocol_compliance(self):
        plugin = GrondwaterPastasPlugin()
        assert isinstance(plugin, Plugin)
        assert plugin.PLUGIN_ID == "grondwater_pastas"

    def test_params_schema_valid(self):
        schema = GrondwaterPastasPlugin.params_schema()
        props = schema["properties"]
        for key in ("aoi_buffer_m", "knmi_station", "tmin", "tmax", "gld_ids", "fit_pastas_models"):
            assert key in props, f"{key} ontbreekt in schema"

    def test_validate_inputs_fit_without_gld_raises(self, tmp_path):
        plugin = GrondwaterPastasPlugin()
        inputs = _make_inputs(tmp_path, fit_pastas_models=True, gld_ids=[])
        with pytest.raises(ValueError, match="gld_ids"):
            plugin.validate_inputs(inputs)

    def test_analyze_with_peilbuizen_and_knmi(self, tmp_path):
        plugin = GrondwaterPastasPlugin()
        inputs = _make_inputs(tmp_path)
        raw = PluginRawData(
            files={
                "peilbuizen_gpkg": str(tmp_path / "peilbuizen.gpkg"),
                "knmi_neerslag": str(tmp_path / "neerslag.csv"),
                "knmi_verdamping": str(tmp_path / "verdamping.csv"),
            },
            metadata={
                "n_peilbuizen": 3,
                "knmi_station": {"id": "310", "name": "Vlissingen", "afstand_km": 15.7},
                "knmi_records": 1000,
                "n_gld_reeksen": 0,
            },
        )
        outputs = plugin.analyze(inputs, raw)
        topics = {c.topic for c in outputs.claims}
        assert "grondwater" in topics
        assert "meteo" in topics
        assert outputs.scope.uncertainty_level == "laag"
        assert any("BRO peilbuizen" in q.name for q in outputs.qgis_layers)

    def test_analyze_without_data(self, tmp_path):
        plugin = GrondwaterPastasPlugin()
        inputs = _make_inputs(tmp_path)
        raw = PluginRawData(
            files={},
            metadata={"n_peilbuizen": 0, "n_gld_reeksen": 0, "knmi_records": 0},
        )
        outputs = plugin.analyze(inputs, raw)
        assert outputs.scope.uncertainty_level == "hoog"
        assert len(outputs.claims) == 0

    def test_pastas_fit_skipped_without_extra(self, tmp_path):
        """Zonder pastas-adapter[full] moet plugin gracefully fail."""
        plugin = GrondwaterPastasPlugin()
        inputs = _make_inputs(
            tmp_path, gld_ids=["GLD001"], fit_pastas_models=True
        )

        # Fake een GLD-tijdreeks (kort, < 30 metingen → wordt geskipt)
        gld_series = pd.Series(
            [0.5, 0.6, 0.7],
            index=pd.date_range("2000-01-01", periods=3, freq="D"),
            name="GLD001",
        )

        raw = PluginRawData(
            files={f"gld_GLD001": str(tmp_path / "GLD001.csv")},
            metadata={
                "n_peilbuizen": 0,
                "n_gld_reeksen": 1,
                "knmi_records": 1000,
                "knmi_station": {"id": "310", "name": "Vlissingen", "afstand_km": 15.7},
            },
        )
        raw.set_frame("neerslag", _fake_neerslag())
        raw.set_frame("verdamping", _fake_verdamping())
        raw.set_frame("gld_GLD001", gld_series)

        outputs = plugin.analyze(inputs, raw)
        # Plugin loopt; te weinig metingen → not_tested wordt gevuld
        not_tested_text = " ".join(outputs.scope.not_tested)
        assert "GLD001" in not_tested_text or "PASTAS" in not_tested_text

    def test_pastastore_written_with_gld_and_knmi(self, tmp_path):
        """Plugin schrijft KNMI-stresses + GLD-oseries naar PastaStore zodat
        pastasdash de data later interactief kan tonen — ook zonder PASTAS-fit."""
        import numpy as np

        plugin = GrondwaterPastasPlugin()
        inputs = _make_inputs(tmp_path, gld_ids=["GLD001"], fit_pastas_models=False)

        # 2 jaar synthetische GLD-tijdreeks (voldoende voor add_oseries)
        rng = np.random.default_rng(42)
        gld_idx = pd.date_range("2000-01-01", periods=730, freq="D", name="Datum")
        gld_series = pd.Series(
            -1.5 + 0.3 * rng.standard_normal(730),
            index=gld_idx,
            name="GLD001",
        )

        raw = PluginRawData(
            files={f"gld_GLD001": str(tmp_path / "GLD001.csv")},
            metadata={
                "n_peilbuizen": 0,
                "n_gld_reeksen": 1,
                "knmi_records": 1000,
                "knmi_station": {"id": "310", "name": "Vlissingen", "afstand_km": 15.7},
            },
        )
        raw.set_frame("neerslag", _fake_neerslag())
        raw.set_frame("verdamping", _fake_verdamping())
        raw.set_frame("gld_GLD001", gld_series)

        outputs = plugin.analyze(inputs, raw)

        assert "pastastore_dir" in outputs.artifacts
        store_dir = Path(outputs.artifacts["pastastore_dir"])
        assert store_dir.exists()
        assert (store_dir / "stresses").exists()
        assert (store_dir / "oseries").exists()

    @pytest.mark.asyncio
    async def test_fetch_data_calls_skills(self, tmp_path):
        plugin = GrondwaterPastasPlugin()
        inputs = _make_inputs(tmp_path)

        with patch(
            "geo_stack.skills.bro.peilbuizen.fetch_peilbuizen",
            return_value=_fake_pbz_gdf(),
        ), patch(
            "geo_stack.skills.knmi.fetch_recharge_inputs",
            return_value=(_fake_neerslag(), _fake_verdamping()),
        ):
            raw = await plugin.fetch_data(inputs)

        assert raw.metadata["n_peilbuizen"] == 3
        assert raw.metadata["knmi_records"] == 1000
        assert raw.metadata["knmi_station"]["id"] == "310"
        assert "peilbuizen_gpkg" in raw.files
        assert "knmi_neerslag" in raw.files
