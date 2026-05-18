"""Smoke-tests voor geo_stack.core.geo_utils."""

import pytest
from geo_stack.core.geo_utils import (
    CRSValidationError,
    hash_bbox,
    validate_bbox,
    validate_rd_crs,
)


def test_validate_rd_crs_ok(rd_gdf):
    assert validate_rd_crs(rd_gdf) is True


def test_validate_rd_crs_wrong_epsg(wgs84_gdf):
    with pytest.raises(CRSValidationError, match="EPSG:4326"):
        validate_rd_crs(wgs84_gdf, strict=True)


def test_validate_rd_crs_non_strict(wgs84_gdf):
    assert validate_rd_crs(wgs84_gdf, strict=False) is False


def test_validate_bbox_valid(rd_bbox):
    result = validate_bbox(rd_bbox, must_be_rd=True)
    assert result == rd_bbox


def test_validate_bbox_wrong_order():
    with pytest.raises(ValueError, match="ongeldige coördinaten"):
        validate_bbox((100_000.0, 400_000.0, 50_000.0, 450_000.0))


def test_validate_bbox_outside_rd():
    with pytest.raises(ValueError, match="buiten plausibel RD"):
        validate_bbox((0.0, 0.0, 1.0, 1.0), must_be_rd=True)


def test_hash_bbox_deterministic(rd_bbox):
    assert hash_bbox(rd_bbox) == hash_bbox(rd_bbox)
    assert len(hash_bbox(rd_bbox)) == 10


def test_hash_bbox_different_inputs(rd_bbox):
    other = (rd_bbox[0] + 1, rd_bbox[1], rd_bbox[2], rd_bbox[3])
    assert hash_bbox(rd_bbox) != hash_bbox(other)
