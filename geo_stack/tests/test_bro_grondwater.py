"""Smoke-tests voor geo_stack.skills.bro_grondwater — geen netwerk.

HTTP-calls worden gemockt. Tests verifiëren:
- WCS GetCoverage URL/parameter-bouw
- product-validatie
- Content-Type check (geen HTML/JSON als raster verwacht wordt)
- peilbuizen-wrapper voegt gmw_detail_url + gld_base_url toe
- foutwrapping naar GrondwaterFetchError
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# PROJ_LIB-conflict fix — zie test_besi.py voor toelichting.
from pyproj.datadir import get_data_dir as _get_proj_data_dir
os.environ.setdefault("PROJ_DATA", _get_proj_data_dir())

import geopandas as gpd
import pytest
import requests
from shapely.geometry import Point

from geo_stack.skills.bro_grondwater import (
    GMW_DETAIL_URL_TEMPLATE,
    GrondwaterFetchError,
    VALID_PRODUCTS,
    fetch_grondwaterstand,
    fetch_peilbuizen,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_tiff_response(tiff_bytes: bytes) -> MagicMock:
    resp = MagicMock()
    resp.headers = {"Content-Type": "image/tiff"}
    resp.content = tiff_bytes
    resp.iter_content.return_value = iter([tiff_bytes])
    resp.raise_for_status.return_value = None
    return resp


def _mock_html_response() -> MagicMock:
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html"}
    resp.content = b"<html>Service Exception</html>"
    resp.iter_content.return_value = iter([resp.content])
    resp.raise_for_status.return_value = None
    return resp


def _mock_session(response: MagicMock) -> MagicMock:
    sess = MagicMock()
    sess.get.return_value = response
    return sess


@pytest.fixture
def rd_bbox_small() -> tuple[float, float, float, float]:
    """Klein BBOX in Flevoland (5×5 km)."""
    return (155_000.0, 495_000.0, 160_000.0, 500_000.0)


# ---------------------------------------------------------------------------
# fetch_grondwaterstand — validatie
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_grondwaterstand_invalid_product(rd_bbox_small):
    with pytest.raises(GrondwaterFetchError, match="product moet"):
        fetch_grondwaterstand(rd_bbox_small, product="UFO")


@pytest.mark.unit
def test_fetch_grondwaterstand_invalid_bbox_order():
    with pytest.raises(ValueError, match="ongeldige coördinaten"):
        fetch_grondwaterstand(
            (160_000.0, 500_000.0, 155_000.0, 495_000.0), product="GHG"
        )


@pytest.mark.unit
def test_valid_products_covers_three_required():
    assert VALID_PRODUCTS == {"GHG", "GLG", "GVG"}


# ---------------------------------------------------------------------------
# fetch_grondwaterstand — URL / params
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_grondwaterstand_builds_wcs_params(rd_bbox_small, tmp_path):
    captured: dict = {}

    def fake_get(url, params=None, timeout=None, stream=False):
        captured["url"] = url
        captured["params"] = params
        # Geef minimale geldige header zodat de check slaagt;
        # content schrijven we naar het tempfile.
        return _mock_tiff_response(b"\x49\x49\x2a\x00")  # TIFF magic bytes

    sess = MagicMock()
    sess.get = fake_get

    with patch(
        "geo_stack.skills.bro_grondwater.http_session", return_value=sess
    ), patch(
        "geo_stack.skills.bro_grondwater._stamp_metadata"
    ):
        out = fetch_grondwaterstand(
            rd_bbox_small,
            product="GHG",
            output_path=tmp_path / "ghg.tif",
            resolution_m=25.0,
        )

    p = captured["params"]
    assert p["service"] == "WCS"
    assert p["request"] == "GetCoverage"
    assert p["coverageId"] == "GHG"
    assert p["format"] == "image/tiff"
    # subset is list met X/Y ranges
    assert any("X(155000" in s for s in p["subset"])
    assert any("Y(495000" in s for s in p["subset"])
    # 5000m / 25m = 200 px in beide richtingen
    assert p["scaleSize"] == "X(200),Y(200)"
    assert out.exists()


@pytest.mark.unit
def test_fetch_grondwaterstand_custom_coverage_id(rd_bbox_small, tmp_path):
    captured: dict = {}

    def fake_get(url, params=None, timeout=None, stream=False):
        captured["params"] = params
        return _mock_tiff_response(b"\x49\x49\x2a\x00")

    sess = MagicMock()
    sess.get = fake_get
    with patch(
        "geo_stack.skills.bro_grondwater.http_session", return_value=sess
    ), patch(
        "geo_stack.skills.bro_grondwater._stamp_metadata"
    ):
        fetch_grondwaterstand(
            rd_bbox_small, product="GHG",
            coverage_id="custom_GHG_v2",
            output_path=tmp_path / "out.tif",
        )

    assert captured["params"]["coverageId"] == "custom_GHG_v2"


@pytest.mark.unit
def test_fetch_grondwaterstand_writes_geotiff(rd_bbox_small, tmp_path):
    payload = b"\x49\x49\x2a\x00" + b"\x00" * 256  # TIFF magic + filler
    sess = _mock_session(_mock_tiff_response(payload))

    with patch(
        "geo_stack.skills.bro_grondwater.http_session", return_value=sess
    ), patch(
        "geo_stack.skills.bro_grondwater._stamp_metadata"
    ):
        out = fetch_grondwaterstand(
            rd_bbox_small, product="GLG", output_path=tmp_path / "glg.tif"
        )

    assert out.exists()
    assert out.read_bytes() == payload


@pytest.mark.unit
def test_fetch_grondwaterstand_default_output_path(rd_bbox_small, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sess = _mock_session(_mock_tiff_response(b"\x49\x49\x2a\x00"))

    with patch(
        "geo_stack.skills.bro_grondwater.http_session", return_value=sess
    ), patch(
        "geo_stack.skills.bro_grondwater._stamp_metadata"
    ):
        out = fetch_grondwaterstand(rd_bbox_small, product="GVG")

    assert out.name.startswith("grondwater_gvg_")
    assert out.suffix == ".tif"


# ---------------------------------------------------------------------------
# fetch_grondwaterstand — error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_grondwaterstand_html_response_raises(rd_bbox_small, tmp_path):
    sess = _mock_session(_mock_html_response())
    with patch(
        "geo_stack.skills.bro_grondwater.http_session", return_value=sess
    ):
        with pytest.raises(GrondwaterFetchError, match="Content-Type"):
            fetch_grondwaterstand(
                rd_bbox_small, product="GHG", output_path=tmp_path / "x.tif"
            )


@pytest.mark.unit
def test_fetch_grondwaterstand_network_error_wrapped(rd_bbox_small, tmp_path):
    sess = MagicMock()
    sess.get.side_effect = requests.RequestException("connection reset")
    with patch(
        "geo_stack.skills.bro_grondwater.http_session", return_value=sess
    ):
        with pytest.raises(GrondwaterFetchError, match="WCS fetch mislukt"):
            fetch_grondwaterstand(
                rd_bbox_small, product="GHG", output_path=tmp_path / "x.tif"
            )


# ---------------------------------------------------------------------------
# fetch_peilbuizen — wrapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_peilbuizen_adds_url_columns(rd_bbox_small):
    fake_gdf = gpd.GeoDataFrame(
        {
            "bro_id": ["GMW000000001234", "GMW000000005678"],
            "well_code": ["B25A0001", "B25A0002"],
            "ground_level_m_nap": [-3.0, -3.2],
            "screen_top_m_nap": [-5.0, -6.0],
            "screen_bottom_m_nap": [-7.0, -8.0],
        },
        geometry=[Point(157_500, 497_500), Point(158_000, 498_000)],
        crs="EPSG:28992",
    )

    with patch(
        "geo_stack.skills.bro_grondwater._fetch_peilbuizen_rest",
        return_value=fake_gdf,
    ):
        out = fetch_peilbuizen(rd_bbox_small)

    assert "gmw_detail_url" in out.columns
    assert "gld_base_url" in out.columns
    assert out.iloc[0]["gmw_detail_url"] == GMW_DETAIL_URL_TEMPLATE.format(
        bro_id="GMW000000001234"
    )
    assert out["gld_base_url"].nunique() == 1  # zelfde voor elke rij


@pytest.mark.unit
def test_fetch_peilbuizen_empty_passthrough(rd_bbox_small):
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
    with patch(
        "geo_stack.skills.bro_grondwater._fetch_peilbuizen_rest",
        return_value=empty,
    ):
        out = fetch_peilbuizen(rd_bbox_small)

    assert out.empty
    assert out.crs.to_epsg() == 28992


@pytest.mark.unit
def test_fetch_peilbuizen_wraps_brofetcherror(rd_bbox_small):
    from geo_stack.skills.bro.peilbuizen import BROFetchError

    with patch(
        "geo_stack.skills.bro_grondwater._fetch_peilbuizen_rest",
        side_effect=BROFetchError("REST endpoint down"),
    ):
        with pytest.raises(GrondwaterFetchError, match="REST endpoint down"):
            fetch_peilbuizen(rd_bbox_small)


@pytest.mark.unit
def test_fetch_peilbuizen_preserves_existing_attrs(rd_bbox_small):
    fake_gdf = gpd.GeoDataFrame(
        {
            "bro_id": ["GMW000000001234"],
            "well_code": ["B25A0001"],
            "ground_level_m_nap": [-3.0],
            "screen_top_m_nap": [-5.0],
            "screen_bottom_m_nap": [-7.0],
            "tube_status": ["gebruiksklaar"],
        },
        geometry=[Point(157_500, 497_500)],
        crs="EPSG:28992",
    )
    with patch(
        "geo_stack.skills.bro_grondwater._fetch_peilbuizen_rest",
        return_value=fake_gdf,
    ):
        out = fetch_peilbuizen(rd_bbox_small)

    # Bestaande kolommen mogen niet verdwijnen
    for col in ("bro_id", "well_code", "ground_level_m_nap",
                "screen_top_m_nap", "tube_status"):
        assert col in out.columns
