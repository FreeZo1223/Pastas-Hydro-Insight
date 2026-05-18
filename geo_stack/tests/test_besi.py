"""Smoke-tests voor geo_stack.skills.besi_fetcher.

Geen netwerk vereist: alle tests werken met een synthetische 2-banden VRT
en minimale metadata-CSV in pytest tmp_path.
"""

from __future__ import annotations

import os
from pathlib import Path

# PROJ_LIB points to PostgreSQL's older PostGIS proj.db on this machine.
# PROJ_DATA overrides PROJ_LIB (PROJ 9.1+) and must be set before rasterio
# initialises GDAL. pyproj bundles its own up-to-date proj.db.
from pyproj.datadir import get_data_dir as _get_proj_data_dir
os.environ.setdefault("PROJ_DATA", _get_proj_data_dir())

import numpy as np
import pytest
import rasterio
from pyproj import CRS as ProjCRS
from rasterio.transform import from_origin
from shapely.geometry import box

from geo_stack.skills.besi_fetcher import BesiFetchError, BesiResult, fetch_besi_for_geometry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORIGIN_X = 100_000.0
_ORIGIN_Y = 400_000.0
_PIXEL_SIZE = 25.0
_N_ROWS = 3
_N_COLS = 3

# Byte values encode probability as value/255.
# Akkerboterbloem: 128 → 0.502 > cutoff 0.4 → present
# Adder:           100 → 0.392 < cutoff 0.7 → absent
_VAL_AKKERBOTERBLOEM = 128
_VAL_ADDER = 100


def _write_tif(path: Path, value: int) -> None:
    transform = from_origin(_ORIGIN_X, _ORIGIN_Y, _PIXEL_SIZE, _PIXEL_SIZE)
    crs = rasterio.crs.CRS.from_epsg(28992)
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=_N_ROWS, width=_N_COLS,
        count=1, dtype="uint8",
        crs=crs, transform=transform,
    ) as dst:
        dst.write(np.full((1, _N_ROWS, _N_COLS), value, dtype=np.uint8))


def _write_vrt(path: Path, tif1: Path, tif2: Path) -> None:
    srs_wkt = ProjCRS.from_epsg(28992).to_wkt()
    vrt_xml = (
        f'<VRTDataset rasterXSize="{_N_COLS}" rasterYSize="{_N_ROWS}">\n'
        f"  <SRS>{srs_wkt}</SRS>\n"
        f"  <GeoTransform>{_ORIGIN_X}, {_PIXEL_SIZE}, 0.0, "
        f"{_ORIGIN_Y}, 0.0, -{_PIXEL_SIZE}</GeoTransform>\n"
        "  <VRTRasterBand dataType=\"Byte\" band=\"1\">\n"
        "    <SimpleSource>\n"
        f"      <SourceFilename relativeToVRT=\"1\">{tif1.name}</SourceFilename>\n"
        "      <SourceBand>1</SourceBand>\n"
        f"      <SrcRect xOff=\"0\" yOff=\"0\" xSize=\"{_N_COLS}\" ySize=\"{_N_ROWS}\"/>\n"
        f"      <DstRect xOff=\"0\" yOff=\"0\" xSize=\"{_N_COLS}\" ySize=\"{_N_ROWS}\"/>\n"
        "    </SimpleSource>\n"
        "  </VRTRasterBand>\n"
        "  <VRTRasterBand dataType=\"Byte\" band=\"2\">\n"
        "    <SimpleSource>\n"
        f"      <SourceFilename relativeToVRT=\"1\">{tif2.name}</SourceFilename>\n"
        "      <SourceBand>1</SourceBand>\n"
        f"      <SrcRect xOff=\"0\" yOff=\"0\" xSize=\"{_N_COLS}\" ySize=\"{_N_ROWS}\"/>\n"
        f"      <DstRect xOff=\"0\" yOff=\"0\" xSize=\"{_N_COLS}\" ySize=\"{_N_ROWS}\"/>\n"
        "    </SimpleSource>\n"
        "  </VRTRasterBand>\n"
        "</VRTDataset>\n"
    )
    path.write_text(vrt_xml, encoding="utf-8")


def _write_metadata(path: Path) -> None:
    path.write_text(
        "dutch_name,scientific_name,species_group,broad_group,"
        "rl_category,habitat_directive,cutoff_value,weight\n"
        "Akkerboterbloem,Ranunculus arvensis,Planten,Planten,LC,,0.4,1\n"
        "Adder,Vipera berus,Reptielen,Reptielen,VU,,0.7,3\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_besi(tmp_path: Path):
    """Maak een minimale 2-bands VRT met metadata in tmp_path."""
    tif1 = tmp_path / "Akkerboterbloem_cog.tif"
    tif2 = tmp_path / "Adder_cog.tif"
    vrt = tmp_path / "test_besi.vrt"
    meta = tmp_path / "species_metadata.csv"

    _write_tif(tif1, _VAL_AKKERBOTERBLOEM)
    _write_tif(tif2, _VAL_ADDER)
    _write_vrt(vrt, tif1, tif2)
    _write_metadata(meta)

    geom = box(
        _ORIGIN_X,
        _ORIGIN_Y - _N_ROWS * _PIXEL_SIZE,
        _ORIGIN_X + _N_COLS * _PIXEL_SIZE,
        _ORIGIN_Y,
    )
    return {"vrt": vrt, "meta": meta, "geom": geom, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_besi_result_type(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert isinstance(result, BesiResult)


@pytest.mark.unit
def test_besi_species_table_columns(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    expected_cols = {
        "dutch_name", "scientific_name", "species_group", "rl_category",
        "habitat_directive", "weight", "cutoff_value", "present",
        "area_ha", "mean_score", "max_score",
    }
    assert expected_cols.issubset(result.species_table.columns)


@pytest.mark.unit
def test_besi_two_species_in_table(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert len(result.species_table) == 2


@pytest.mark.unit
def test_besi_presence_above_cutoff(synthetic_besi):
    """Akkerboterbloem (0.50 > 0.40 cutoff) moet present=True zijn."""
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    row = result.species_table[result.species_table["dutch_name"] == "Akkerboterbloem"].iloc[0]
    assert row["present"] is True or bool(row["present"])


@pytest.mark.unit
def test_besi_absence_below_cutoff(synthetic_besi):
    """Adder (0.39 < 0.70 cutoff) moet present=False zijn."""
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    row = result.species_table[result.species_table["dutch_name"] == "Adder"].iloc[0]
    assert not (row["present"] is True or bool(row["present"]))


@pytest.mark.unit
def test_besi_n_species_present(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert result.n_species_present == 1


@pytest.mark.unit
def test_besi_richness_array_shape(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert result.richness_array.ndim == 2
    assert result.richness_array.max() <= 2


@pytest.mark.unit
def test_besi_priority_array_values(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert result.priority_array.ndim == 2
    assert set(np.unique(result.priority_array).tolist()).issubset({0, 1, 2, 3, 4, 5})


@pytest.mark.unit
def test_besi_data_confidence_field(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert result.data_confidence == "model_based_probability"


@pytest.mark.unit
def test_besi_area_ha_positive(synthetic_besi):
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    assert result.area_ha > 0.0


@pytest.mark.unit
def test_besi_cutoff_value_is_uncertainty_marker(synthetic_besi):
    """cutoff_value kolom aanwezig als UI-onzekerheidsmarker."""
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
    )
    cutoffs = result.species_table["cutoff_value"]
    assert (cutoffs > 0).all()
    assert (cutoffs <= 1).all()


@pytest.mark.unit
def test_besi_missing_vrt_raises(synthetic_besi):
    with pytest.raises(BesiFetchError, match="VRT"):
        fetch_besi_for_geometry(
            geom=synthetic_besi["geom"],
            vrt_path=synthetic_besi["tmp"] / "does_not_exist.vrt",
            metadata_path=synthetic_besi["meta"],
        )


@pytest.mark.unit
def test_besi_no_vrt_path_raises():
    """Geen vrt_path en geen BESI_VRT_PATH env → BesiFetchError."""
    import os
    env_backup = os.environ.pop("BESI_VRT_PATH", None)
    try:
        with pytest.raises(BesiFetchError, match="BESI_VRT_PATH"):
            fetch_besi_for_geometry(geom=box(0, 0, 100, 100))
    finally:
        if env_backup is not None:
            os.environ["BESI_VRT_PATH"] = env_backup


@pytest.mark.unit
def test_besi_species_group_filter(synthetic_besi):
    """species_group='Planten' geeft alleen Akkerboterbloem terug."""
    result = fetch_besi_for_geometry(
        geom=synthetic_besi["geom"],
        vrt_path=synthetic_besi["vrt"],
        metadata_path=synthetic_besi["meta"],
        species_group="Planten",
    )
    assert len(result.species_table) == 1
    assert result.species_table.iloc[0]["dutch_name"] == "Akkerboterbloem"


@pytest.mark.unit
def test_besi_unknown_species_group_raises(synthetic_besi):
    with pytest.raises(BesiFetchError, match="Soortengroep"):
        fetch_besi_for_geometry(
            geom=synthetic_besi["geom"],
            vrt_path=synthetic_besi["vrt"],
            metadata_path=synthetic_besi["meta"],
            species_group="BestaatNiet",
        )
