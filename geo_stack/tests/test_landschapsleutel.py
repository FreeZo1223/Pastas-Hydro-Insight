"""Smoke-tests voor geo_stack.skills.landschapsleutel — geen netwerk.

HTTP-calls worden gemockt. Tests verifiëren:
- BBOX-validatie (ongeldige volgorde)
- Lege FGR → lege GeoDataFrame terug
- Lege bodemkaart → lege GeoDataFrame terug
- Aanwezigheid en correctheid van uitvoerkolommen
- Spatial join verrijkt bodemvlakken met FGR-regio
- Kolom-aliassen (naam, regio, BktNm, gt, ...) worden correct gemapped
- BROFetchError wordt gewrapped naar LandschapsclassificatieFetchError
- FGR WFS-fout wordt gewrapped
- output_path schrijft een bestand
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# PROJ_LIB-conflict fix — PostGIS-proj.db is te oud voor rasterio/pyproj
from pyproj.datadir import get_data_dir as _get_proj_data_dir
os.environ.setdefault("PROJ_DATA", _get_proj_data_dir())

import geopandas as gpd
import pytest
from shapely.geometry import box

from geo_stack.skills.bro.bodemkaart import BROFetchError
from geo_stack.skills.landschapsleutel import (
    LandschapsclassificatieFetchError,
    OUTPUT_COLUMNS,
    classify_landscape,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _fgr_gdf(regio: str = "Hogere zandgronden") -> gpd.GeoDataFrame:
    """Minimaal FGR GeoDataFrame met standaardkolomnaam 'naam'."""
    return gpd.GeoDataFrame(
        {"naam": [regio]},
        geometry=[box(100_000, 400_000, 250_000, 600_000)],
        crs="EPSG:28992",
    )


def _bodem_gdf() -> gpd.GeoDataFrame:
    """Minimaal bodemkaart GeoDataFrame met standaardkolomnamen."""
    return gpd.GeoDataFrame(
        {"bodemtype": ["Hn21"], "gt_klasse": ["VIo"]},
        geometry=[box(155_000, 495_000, 160_000, 500_000)],
        crs="EPSG:28992",
    )


@pytest.fixture
def rd_bbox_small() -> tuple[float, float, float, float]:
    """Klein BBOX in Flevoland (5×5 km)."""
    return (155_000.0, 495_000.0, 160_000.0, 500_000.0)


# ---------------------------------------------------------------------------
# BBOX-validatie
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_invalid_bbox_order():
    with pytest.raises(ValueError, match="ongeldige coördinaten"):
        classify_landscape((160_000.0, 500_000.0, 155_000.0, 495_000.0))


# ---------------------------------------------------------------------------
# Lege-doorvoer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_empty_fgr_returns_empty(rd_bbox_small):
    empty_fgr = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=empty_fgr,
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    assert result.empty
    assert result.crs.to_epsg() == 28992


@pytest.mark.unit
def test_classify_landscape_empty_bodemkaart_returns_empty(rd_bbox_small):
    empty_bodem = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=empty_bodem,
    ):
        result = classify_landscape(rd_bbox_small)

    assert result.empty
    assert result.crs.to_epsg() == 28992


# ---------------------------------------------------------------------------
# Uitvoerkolommen en CRS
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_has_required_columns(rd_bbox_small):
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    for col in OUTPUT_COLUMNS:
        assert col in result.columns, f"Ontbrekende kolom: {col}"
    assert "geometry" in result.columns


@pytest.mark.unit
def test_classify_landscape_output_crs_is_rd(rd_bbox_small):
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    assert result.crs.to_epsg() == 28992


# ---------------------------------------------------------------------------
# Spatial join — inhoud
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_joins_fgr_regio(rd_bbox_small):
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf("Rivierengebied"),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    assert len(result) == 1
    assert result.iloc[0]["fgr_regio"] == "Rivierengebied"


@pytest.mark.unit
def test_classify_landscape_preserves_bodem_columns(rd_bbox_small):
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    row = result.iloc[0]
    assert row["bodemtype"] == "Hn21"
    assert row["gt_klasse"] == "VIo"


# ---------------------------------------------------------------------------
# Kolom-aliassen
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_fgr_alias_regio(rd_bbox_small):
    """'regio' als kolomnaam in FGR → wordt gemapped naar fgr_regio."""
    fgr = gpd.GeoDataFrame(
        {"regio": ["Laagveen"]},
        geometry=[box(100_000, 400_000, 250_000, 600_000)],
        crs="EPSG:28992",
    )
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=fgr,
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    assert result.iloc[0]["fgr_regio"] == "Laagveen"


@pytest.mark.unit
def test_classify_landscape_bodem_alias_BktNm(rd_bbox_small):
    """'BktNm' als kolomnaam in bodemkaart → wordt gemapped naar bodemtype."""
    bodem = gpd.GeoDataFrame(
        {"BktNm": ["pZn21"], "Gt": ["IIIb"]},
        geometry=[box(155_000, 495_000, 160_000, 500_000)],
        crs="EPSG:28992",
    )
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=bodem,
    ):
        result = classify_landscape(rd_bbox_small)

    assert result.iloc[0]["bodemtype"] == "pZn21"
    assert result.iloc[0]["gt_klasse"] == "IIIb"


@pytest.mark.unit
def test_classify_landscape_missing_sectie_serie_is_none(rd_bbox_small):
    """FGR zonder sectie/serie → fgr_sectie en fgr_serie zijn None."""
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small)

    assert result.iloc[0]["fgr_sectie"] is None
    assert result.iloc[0]["fgr_serie"] is None


# ---------------------------------------------------------------------------
# Foutafhandeling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_wraps_brofetcherror(rd_bbox_small):
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        side_effect=BROFetchError("bodemkaart service down"),
    ):
        with pytest.raises(
            LandschapsclassificatieFetchError, match="bodemkaart service down"
        ):
            classify_landscape(rd_bbox_small)


@pytest.mark.unit
def test_classify_landscape_wraps_fgr_fetch_error(rd_bbox_small):
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        side_effect=LandschapsclassificatieFetchError("FGR WFS fetch mislukt"),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        with pytest.raises(
            LandschapsclassificatieFetchError, match="FGR WFS fetch mislukt"
        ):
            classify_landscape(rd_bbox_small)


@pytest.mark.unit
def test_classify_landscape_wraps_unexpected_fgr_error(rd_bbox_small):
    """Onverwachte exception uit _fetch_fgr → LandschapsclassificatieFetchError."""
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        side_effect=RuntimeError("unexpected"),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        with pytest.raises(LandschapsclassificatieFetchError, match="FGR fetch mislukt"):
            classify_landscape(rd_bbox_small)


# ---------------------------------------------------------------------------
# output_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_landscape_writes_output_file(rd_bbox_small, tmp_path):
    out = tmp_path / "landschap.gpkg"
    with patch(
        "geo_stack.skills.landschapsleutel._fetch_fgr",
        return_value=_fgr_gdf(),
    ), patch(
        "geo_stack.skills.landschapsleutel.fetch_bodemkaart",
        return_value=_bodem_gdf(),
    ):
        result = classify_landscape(rd_bbox_small, output_path=out)

    assert out.exists()
    assert len(result) == 1


# ---------------------------------------------------------------------------
# output_columns completeness constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_output_columns_constant():
    assert set(OUTPUT_COLUMNS) == {
        "fgr_regio", "fgr_sectie", "fgr_serie", "bodemtype", "gt_klasse"
    }
