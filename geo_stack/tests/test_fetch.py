"""Tests voor de smart fetch-dispatcher (cloud-native eerst)."""

from __future__ import annotations

from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import box

from geo_stack import fetch
from geo_stack.fetch import (
    NoBackendAvailableError,
    UnknownDatasetError,
    fetch_features,
    list_datasets,
)


@pytest.fixture
def fake_yaml(tmp_path):
    """Minimale yaml met cloud-native, alleen-fallback, en alleen-cloud datasets."""
    p = tmp_path / "data_sources.yaml"
    p.write_text(
        """
services:
  bag_3d:
    - label: 3DBAG cloud-native
      cloud_native_url: "https://data.3dbag.nl/v20250903/3dbag_nl.gpkg.zip"
      service_type: CLOUD_NATIVE
  bgt:
    - label: BGT WFS
      endpoint: "https://service.pdok.nl/lv/bgt/wfs/v1_0"
      service_type: WFS
  unknown_dataset:
    - label: hypothetisch
      endpoint: "https://example.com"
      service_type: WFS
""",
        encoding="utf-8",
    )
    return p


def _make_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(125_000, 460_000, 145_000, 480_000)],
        crs="EPSG:28992",
    )


class TestFetchFeatures:
    def test_unknown_dataset_raises(self, fake_yaml):
        with pytest.raises(UnknownDatasetError):
            fetch_features(
                "doesnotexist",
                bbox=(125_000, 460_000, 145_000, 480_000),
                data_sources_yaml=fake_yaml,
            )

    def test_invalid_bbox_raises(self, fake_yaml):
        with pytest.raises(ValueError):
            fetch_features(
                "bag_3d",
                bbox=(4.5, 52.0, 5.5, 53.0),  # WGS84
                data_sources_yaml=fake_yaml,
            )

    def test_cloud_native_used_when_available(self, fake_yaml):
        from unittest.mock import MagicMock

        mock_cn = MagicMock(return_value=_make_gdf())
        mock_cn.__name__ = "mock_cn"
        with patch.dict(fetch._CLOUD_NATIVE_DISPATCH, {"bag_3d": mock_cn}):
            result = fetch_features(
                "bag_3d",
                bbox=(125_000, 460_000, 145_000, 480_000),
                data_sources_yaml=fake_yaml,
            )
            mock_cn.assert_called_once()
            assert isinstance(result, gpd.GeoDataFrame)

    def test_falls_back_when_cloud_native_fails(self, fake_yaml):
        from unittest.mock import MagicMock

        mock_cn = MagicMock(side_effect=RuntimeError("boom"))
        mock_cn.__name__ = "mock_cn"
        with patch.dict(fetch._CLOUD_NATIVE_DISPATCH, {"bag_3d": mock_cn}):
            # bag_3d heeft geen fallback → moet NoBackendAvailable raisen
            with pytest.raises(NoBackendAvailableError):
                fetch_features(
                    "bag_3d",
                    bbox=(125_000, 460_000, 145_000, 480_000),
                    data_sources_yaml=fake_yaml,
                )

    def test_uses_fallback_when_no_cloud_native(self, fake_yaml):
        """BGT heeft geen cloud_native_url → moet direct WFS-fallback gebruiken."""
        from unittest.mock import MagicMock

        mock_fb = MagicMock(return_value=_make_gdf())
        mock_fb.__name__ = "mock_fb"
        with patch.dict(fetch._FALLBACK_DISPATCH, {"bgt": mock_fb}):
            result = fetch_features(
                "bgt",
                bbox=(125_000, 460_000, 145_000, 480_000),
                data_sources_yaml=fake_yaml,
                feature_type="bgt:pand",
            )
            mock_fb.assert_called_once()
            assert isinstance(result, gpd.GeoDataFrame)

    def test_prefer_cloud_native_false_skips_cloud_native(self, fake_yaml):
        """prefer_cloud_native=False moet meteen naar fallback gaan, ook als cloud-native bestaat."""
        from unittest.mock import MagicMock

        mock_cn = MagicMock(return_value=_make_gdf())
        mock_cn.__name__ = "mock_cn"
        with patch.dict(fetch._CLOUD_NATIVE_DISPATCH, {"bag_3d": mock_cn}):
            # bag_3d heeft geen fallback → NoBackendAvailable verwacht
            with pytest.raises(NoBackendAvailableError):
                fetch_features(
                    "bag_3d",
                    bbox=(125_000, 460_000, 145_000, 480_000),
                    data_sources_yaml=fake_yaml,
                    prefer_cloud_native=False,
                )
            mock_cn.assert_not_called()


class TestListDatasets:
    def test_lists_all_datasets(self, fake_yaml):
        result = list_datasets(data_sources_yaml=fake_yaml)
        assert "bag_3d" in result
        assert "bgt" in result

    def test_marks_cloud_native_availability(self, fake_yaml):
        result = list_datasets(data_sources_yaml=fake_yaml)
        assert result["bag_3d"]["cloud_native"] is True
        assert result["bgt"]["cloud_native"] is False

    def test_marks_fallback_availability(self, fake_yaml):
        result = list_datasets(data_sources_yaml=fake_yaml)
        assert result["bgt"]["fallback"] is True
        assert result["unknown_dataset"]["fallback"] is False
