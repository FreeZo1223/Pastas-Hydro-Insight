"""Pytest fixtures voor geo_stack smoke-tests."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box


@pytest.fixture
def rd_bbox() -> tuple[float, float, float, float]:
    """Kleine BBOX in RD-stelsel (Burgh-Haamstede omgeving)."""
    return (29_000.0, 395_000.0, 34_000.0, 400_000.0)


@pytest.fixture
def rd_gdf(rd_bbox) -> gpd.GeoDataFrame:
    """Eenvoudige GeoDataFrame in EPSG:28992."""
    minx, miny, maxx, maxy = rd_bbox
    return gpd.GeoDataFrame(
        {"id": [1], "naam": ["test"]},
        geometry=[box(minx, miny, maxx, maxy)],
        crs="EPSG:28992",
    )


@pytest.fixture
def wgs84_gdf() -> gpd.GeoDataFrame:
    """GeoDataFrame in WGS84 (voor reproject-tests)."""
    return gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(3.8, 51.6, 3.9, 51.7)],
        crs="EPSG:4326",
    )


@pytest.fixture
def data_sources_yaml(tmp_path) -> Path:
    """Minimale data_sources.yaml als test-fixture."""
    yaml_content = """
services:
  bgt:
    - label: BGT WFS test
      endpoint: "https://service.pdok.nl/lv/bgt/wfs/v1_0"
      service_type: WFS
      source_version: "BGT test"
      update_cadence: dagelijks
      cql_filter: true
  ahn:
    - label: AHN4 WCS test
      endpoint: "https://service.pdok.nl/rws/ahn/wcs/v1_0"
      service_type: WCS
      source_version: "AHN4"
      update_cadence: eenmalig
"""
    p = tmp_path / "data_sources.yaml"
    p.write_text(yaml_content, encoding="utf-8")
    return p
