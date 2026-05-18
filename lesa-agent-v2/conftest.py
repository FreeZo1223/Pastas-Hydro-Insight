"""Root conftest — env-vars instellen vóór enig geo-pakket geladen wordt.

PROJ_DATA moet vóór de eerste rasterio/pyproj-import gezet worden.
Op Windows conflicteert PostgreSQL's gebundelde proj.db met de venv-versie.
Rasterio bundelt zijn eigen PROJ-data (version 1.6); die versie gebruiken
zodat rasterio's GDAL 3.12+ geen DATABASE.LAYOUT.VERSION-conflict geeft.
"""

from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config):
    # Prefer rasterio's bundled PROJ data (version >=6 required by GDAL 3.12+).
    # pyproj ships version 4 which triggers a "wrong PROJ installation" error.
    try:
        import rasterio
        rasterio_proj = Path(rasterio.__file__).parent / "proj_data"
        if (rasterio_proj / "proj.db").exists():
            os.environ["PROJ_DATA"] = str(rasterio_proj)
            os.environ["PROJ_LIB"] = str(rasterio_proj)
            return
    except Exception:
        pass
    # Fallback to pyproj's data directory
    try:
        import pyproj
        proj_dir = pyproj.datadir.get_data_dir()
        os.environ["PROJ_DATA"] = proj_dir
        os.environ["PROJ_LIB"] = proj_dir
    except Exception:
        pass
