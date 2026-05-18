"""Smoke-tests voor geo_stack.skills.locatieserver — geen netwerk.

HTTP-calls worden gemockt via ``unittest.mock``. Tests verifiëren:
- response-parsing naar GeoDataFrame in EPSG:28992
- type-filter wordt correct doorgegeven als fq-parameter
- lege response geeft lege GeoDataFrame (niet None / niet error)
- ongeldige input → LocalisatieFetchError
- netwerk-fout → LocalisatieFetchError (geen requests-exception leak)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from geo_stack.skills.locatieserver import (
    LocalisatieFetchError,
    VALID_TYPES,
    geocode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _mock_session(payload: dict) -> MagicMock:
    sess = MagicMock()
    sess.get.return_value = _mock_response(payload)
    return sess


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adres_payload() -> dict:
    """Realistic Locatieserver respons voor één adres."""
    return {
        "response": {
            "numFound": 1,
            "docs": [{
                "id": "adr-0000000000000001",
                "type": "adres",
                "weergavenaam": "Lange Voorhout 8, 2514ED Den Haag",
                "score": 12.34,
                "bron": "BAG",
                "centroide_rd": "POINT(80957.6 455020.0)",
                "centroide_ll": "POINT(4.3 52.08)",
                "gemeentenaam": "'s-Gravenhage",
                "provincienaam": "Zuid-Holland",
                "woonplaatsnaam": "'s-Gravenhage",
                "straatnaam": "Lange Voorhout",
                "huisnummer": 8,
                "postcode": "2514ED",
            }],
        }
    }


@pytest.fixture
def perceel_payload() -> dict:
    """Locatieserver respons voor één perceel — centroide + lookup-polygon."""
    return {
        "response": {
            "numFound": 1,
            "docs": [{
                "id": "pcl-3f43d0c3aaaa",
                "type": "perceel",
                "weergavenaam": "Lelystad B 10",
                "score": 8.21,
                "bron": "BRK",
                "centroide_rd": "POINT(159000 500000)",
                "kadastrale_grootte": 1234,
            }],
        }
    }


@pytest.fixture
def empty_payload() -> dict:
    return {"response": {"numFound": 0, "docs": []}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_geocode_returns_geodataframe_with_rd_crs(adres_payload):
    with patch(
        "geo_stack.skills.locatieserver.http_session",
        return_value=_mock_session(adres_payload),
    ):
        gdf = geocode("Lange Voorhout 8 Den Haag")

    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 28992


@pytest.mark.unit
def test_geocode_parses_attributes(adres_payload):
    with patch(
        "geo_stack.skills.locatieserver.http_session",
        return_value=_mock_session(adres_payload),
    ):
        gdf = geocode("Lange Voorhout 8 Den Haag")

    row = gdf.iloc[0]
    assert row["weergavenaam"] == "Lange Voorhout 8, 2514ED Den Haag"
    assert row["straatnaam"] == "Lange Voorhout"
    assert row["huisnummer"] == 8
    assert row["postcode"] == "2514ED"
    assert row["bron"] == "BAG"


@pytest.mark.unit
def test_geocode_centroide_falls_within_rd_bounds(adres_payload):
    with patch(
        "geo_stack.skills.locatieserver.http_session",
        return_value=_mock_session(adres_payload),
    ):
        gdf = geocode("test")

    pt = gdf.iloc[0].geometry
    assert 0 < pt.x < 300_000
    assert 290_000 < pt.y < 630_000


@pytest.mark.unit
def test_geocode_empty_response_returns_empty_gdf(empty_payload):
    with patch(
        "geo_stack.skills.locatieserver.http_session",
        return_value=_mock_session(empty_payload),
    ):
        gdf = geocode("nonexistent_xyz_qwerty")

    assert gdf.empty
    assert gdf.crs.to_epsg() == 28992


@pytest.mark.unit
def test_geocode_invalid_type_raises():
    with pytest.raises(LocalisatieFetchError, match="Onbekend type"):
        geocode("test", type="ufo")


@pytest.mark.unit
def test_geocode_rows_too_high_raises():
    with pytest.raises(LocalisatieFetchError, match="rows moet tussen"):
        geocode("test", rows=200)


@pytest.mark.unit
def test_geocode_rows_too_low_raises():
    with pytest.raises(LocalisatieFetchError, match="rows moet tussen"):
        geocode("test", rows=0)


@pytest.mark.unit
def test_geocode_passes_type_filter_as_fq(adres_payload):
    captured: dict = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _mock_response(adres_payload)

    sess = MagicMock()
    sess.get = fake_get
    with patch(
        "geo_stack.skills.locatieserver.http_session", return_value=sess
    ):
        geocode("Lelystad", type="gemeente")

    assert captured["params"]["fq"] == "type:gemeente"
    assert captured["params"]["q"] == "Lelystad"


@pytest.mark.unit
def test_geocode_no_type_means_no_fq(adres_payload):
    captured: dict = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return _mock_response(adres_payload)

    sess = MagicMock()
    sess.get = fake_get
    with patch(
        "geo_stack.skills.locatieserver.http_session", return_value=sess
    ):
        geocode("Lelystad")

    assert "fq" not in captured["params"]


@pytest.mark.unit
def test_geocode_network_error_wrapped(adres_payload):
    sess = MagicMock()
    sess.get.side_effect = requests.RequestException("connection reset")
    with patch(
        "geo_stack.skills.locatieserver.http_session", return_value=sess
    ):
        with pytest.raises(LocalisatieFetchError, match="fetch mislukt"):
            geocode("test")


@pytest.mark.unit
def test_geocode_json_parse_error_wrapped():
    resp = MagicMock()
    resp.json.side_effect = ValueError("not json")
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    with patch(
        "geo_stack.skills.locatieserver.http_session", return_value=sess
    ):
        with pytest.raises(LocalisatieFetchError, match="JSON parse"):
            geocode("test")


@pytest.mark.unit
def test_geocode_skips_docs_without_geometry():
    payload = {
        "response": {
            "numFound": 2,
            "docs": [
                {"id": "1", "type": "adres", "weergavenaam": "leeg-geom"},
                {
                    "id": "2", "type": "adres", "weergavenaam": "met-geom",
                    "centroide_rd": "POINT(150000 460000)",
                },
            ],
        }
    }
    with patch(
        "geo_stack.skills.locatieserver.http_session",
        return_value=_mock_session(payload),
    ):
        gdf = geocode("mixed")

    assert len(gdf) == 1
    assert gdf.iloc[0]["id"] == "2"


@pytest.mark.unit
def test_geocode_full_geometry_calls_lookup(perceel_payload):
    """full_geometry=True moet lookup-endpoint aanroepen voor elke id."""
    lookup_payload = {
        "response": {
            "docs": [{
                "geometrie_rd": (
                    "POLYGON((159000 500000, 159050 500000, "
                    "159050 500050, 159000 500050, 159000 500000))"
                )
            }]
        }
    }
    call_log: list[str] = []

    def fake_get(url, params=None, timeout=None):
        call_log.append(url)
        if url.endswith("/free"):
            return _mock_response(perceel_payload)
        if url.endswith("/lookup"):
            return _mock_response(lookup_payload)
        raise AssertionError(f"unexpected URL {url}")

    sess = MagicMock()
    sess.get = fake_get
    with patch(
        "geo_stack.skills.locatieserver.http_session", return_value=sess
    ):
        gdf = geocode("LLS00-B-10", type="perceel", full_geometry=True)

    assert any(u.endswith("/free") for u in call_log)
    assert any(u.endswith("/lookup") for u in call_log)
    assert gdf.iloc[0].geometry.geom_type == "Polygon"


@pytest.mark.unit
def test_valid_types_covers_expected_set():
    expected = {"adres", "gemeente", "woonplaats", "weg", "postcode",
                "perceel", "buurt", "wijk", "provincie"}
    assert expected.issubset(VALID_TYPES)
