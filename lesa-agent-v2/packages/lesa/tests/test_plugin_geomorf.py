"""Smoke-tests voor geomorfologie_ahn plugin — geen live AHN HTTP.

fetch_data wordt gemockt met een synthetisch DTM-raster. analyze() draait
volledig; we verifiëren claims, scope, artifacts en QGIS-lagen.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from lesa.plugins._base import Plugin, PluginInputs, PluginRawData
from lesa.plugins.geomorfologie_ahn.params import GeomorfologieAhnParams
from lesa.plugins.geomorfologie_ahn.plugin import GeomorfologieAhnPlugin


# ── Helpers ───────────────────────────────────────────────────────────────

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


def _make_dtm_tif(path: Path, *, rows: int = 60, cols: int = 60) -> Path:
    """Schrijf een synthetisch 5m DTM naar disk (EPSG:28992)."""
    # Hoogte: variabel duinpatroon
    rng = np.random.default_rng(42)
    data = (
        rng.normal(loc=1.5, scale=1.2, size=(rows, cols)).astype(np.float32)
    )
    # Voeg een laagte in links-onder
    data[40:, :20] = rng.normal(loc=-0.5, scale=0.2, size=(20, 20))

    transform = from_bounds(25850, 391050, 26150, 391350, cols, rows)
    profile = {
        "driver": "GTiff",
        "dtype": rasterio.float32,
        "width": cols,
        "height": rows,
        "count": 1,
        "crs": "EPSG:28992",
        "transform": transform,
        "nodata": -9999.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(data, 1)
    return path


def _make_inputs(tmp_path: Path) -> PluginInputs:
    artifact_dir = tmp_path / "data" / "geomorfologie_ahn"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return PluginInputs(
        session_id="test-session",
        project_name="Burgh-test",
        scale_level=2,
        landscape_type="duinen",
        aoi_geojson=_SIMPLE_AOI,
        artifact_dir=str(artifact_dir),
        params={"resolution": 5.0, "product": "DTM", "laagte_percentiel": 25.0},
    )


# ── Tests ─────────────────────────────────────────────────────────────────

class TestGeomorfologieAhnPlugin:
    def test_protocol_compliance(self):
        plugin = GeomorfologieAhnPlugin()
        assert isinstance(plugin, Plugin)
        assert plugin.PLUGIN_ID == "geomorfologie_ahn"
        assert plugin.PLUGIN_VERSION == "0.1.0"

    def test_params_schema_valid(self):
        schema = GeomorfologieAhnPlugin.params_schema()
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "resolution" in props
        assert "laagte_percentiel" in props

    def test_validate_inputs_ok(self, tmp_path):
        plugin = GeomorfologieAhnPlugin()
        plugin.validate_inputs(_make_inputs(tmp_path))

    def test_validate_inputs_buffer_too_large_wcs_mode(self, tmp_path):
        # fetch_method='wcs' + 0.5m + grote buffer → fout (WCS-limiet)
        plugin = GeomorfologieAhnPlugin()
        inputs = _make_inputs(tmp_path)
        inputs.params = {"resolution": 0.5, "aoi_buffer_m": 600.0, "fetch_method": "wcs"}
        with pytest.raises(ValueError, match="aoi_buffer_m"):
            plugin.validate_inputs(inputs)

    def test_validate_inputs_buffer_large_auto_mode_ok(self, tmp_path):
        # fetch_method='auto' (default) + 0.5m + grote buffer is OK (COG neemt over)
        plugin = GeomorfologieAhnPlugin()
        inputs = _make_inputs(tmp_path)
        inputs.params = {"resolution": 0.5, "aoi_buffer_m": 600.0, "fetch_method": "auto"}
        plugin.validate_inputs(inputs)  # mag niet gooien

    def test_analyze_with_synthetic_dtm(self, tmp_path):
        plugin = GeomorfologieAhnPlugin()
        inputs = _make_inputs(tmp_path)
        dtm_path = Path(inputs.artifact_dir) / "ahn4_dtm_5.0m.tif"
        _make_dtm_tif(dtm_path)

        raw = PluginRawData(
            files={"dtm": str(dtm_path)},
            metadata={"resolution": 5.0, "product": "DTM"},
        )
        outputs = plugin.analyze(inputs, raw)

        # Minimale claims
        assert len(outputs.claims) >= 2
        topics = {c.topic for c in outputs.claims}
        assert "reliëf" in topics
        assert "laagtegebieden" in topics

        # Scope aanwezig
        assert outputs.scope.scope == "plugin"
        assert outputs.scope.uncertainty_level == "laag"

        # Artifacts
        assert "dtm_tif" in outputs.artifacts
        assert "helling_tif" in outputs.artifacts
        assert Path(outputs.artifacts["helling_tif"]).exists()

        # QGIS-lagen
        names = [l.name for l in outputs.qgis_layers]
        assert "AHN4 DTM" in names
        assert "Helling (graden)" in names

    def test_analyze_summary_keys(self, tmp_path):
        plugin = GeomorfologieAhnPlugin()
        inputs = _make_inputs(tmp_path)
        dtm_path = Path(inputs.artifact_dir) / "ahn4_dtm_5.0m.tif"
        _make_dtm_tif(dtm_path)
        raw = PluginRawData(files={"dtm": str(dtm_path)}, metadata={})
        outputs = plugin.analyze(inputs, raw)

        for key in ("z_min", "z_max", "z_mean", "local_relief_m", "laagte_pct"):
            assert key in outputs.summary, f"{key} ontbreekt in summary"

    @pytest.mark.asyncio
    async def test_fetch_data_calls_ahn_skill(self, tmp_path):
        plugin = GeomorfologieAhnPlugin()
        inputs = _make_inputs(tmp_path)
        dtm_path = Path(inputs.artifact_dir) / "ahn4_dtm_5.0m.tif"
        _make_dtm_tif(dtm_path)

        with patch(
            "geo_stack.skills.ahn.async_fetch_ahn_tile",
            new=AsyncMock(return_value=dtm_path),
        ):
            raw = await plugin.fetch_data(inputs)

        assert "dtm" in raw.files
        assert "resolution" in raw.metadata
