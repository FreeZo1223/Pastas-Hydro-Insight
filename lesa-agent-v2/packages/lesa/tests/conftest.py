"""Gedeelde pytest fixtures voor lesa-package tests."""

from __future__ import annotations

import os

import pytest

# Zet PROJ_DATA naar rasterio's gebundelde PROJ-data (version 1.6).
# pyproj heeft version 4 wat conflicteert met rasterio's GDAL 3.12+ (verwacht >=6).
try:
    import rasterio as _rio
    from pathlib import Path as _Path
    _rasterio_proj = _Path(_rio.__file__).parent / "proj_data"
    if (_rasterio_proj / "proj.db").exists():
        os.environ.setdefault("PROJ_DATA", str(_rasterio_proj))
        os.environ.setdefault("PROJ_LIB", str(_rasterio_proj))
    else:
        import pyproj as _pp
        os.environ.setdefault("PROJ_DATA", _pp.datadir.get_data_dir())
        os.environ.setdefault("PROJ_LIB", _pp.datadir.get_data_dir())
except Exception:
    pass

from lesa.domain.aoi import AOI
from lesa.session.state import SessionState


# ── Burgh-Haamstede test-AOI (RD New / EPSG:28992) ────────────────────────
# Bounding box rond de zandwinplas/ijsbaan in Burgh-Haamstede
# Echte coördinaten: ca. 26200, 391400 (RD)
_BURGH_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [26100.0, 391300.0],
        [26400.0, 391300.0],
        [26400.0, 391600.0],
        [26100.0, 391600.0],
        [26100.0, 391300.0],
    ]],
}


@pytest.fixture
def burgh_aoi() -> AOI:
    """Kleine AOI rondom Burgh-Haamstede (EPSG:28992)."""
    return AOI(
        geometry=_BURGH_POLYGON,
        crs="EPSG:28992",
        name="Burgh-Haamstede testgebied",
        source="user_geojson",
    )


@pytest.fixture
def minimal_session(burgh_aoi: AOI) -> SessionState:
    """Minimale SessionState voor unit-tests."""
    return SessionState(
        project_name="Test Burgh-Haamstede",
        aoi=burgh_aoi,
        scale_level=1,
        landscape_type="duinen",
    )
