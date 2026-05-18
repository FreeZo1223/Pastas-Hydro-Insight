"""Gedeelde helpers voor geo_stack.

Bevat:
- ``validate_rd_crs``  — strikte CRS-validatie tegen EPSG:28992 + bbox-plausibiliteit.
- ``http_session``     — ``requests.Session`` met retry-logica voor PDOK.
- ``BBox``             — typed alias voor (minx, miny, maxx, maxy).
- ``hash_bbox``        — deterministische korte hash voor cache-bestandsnamen.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    import geopandas as gpd

BBox = Tuple[float, float, float, float]

RD_PLAUSIBLE_BOUNDS: BBox = (-7000.0, 290000.0, 300000.0, 630000.0)
RD_EPSG = 28992


class CRSValidationError(ValueError):
    """Raised wanneer een GeoDataFrame niet aan de RD-stelsel-eisen voldoet."""


def validate_rd_crs(
    gdf: "gpd.GeoDataFrame",
    *,
    strict: bool = True,
    check_bounds: bool = True,
) -> bool:
    """Valideer dat ``gdf`` in EPSG:28992 (RD-stelsel) staat."""
    if gdf.crs is None:
        return _fail("CRS is None — RD-stelsel (EPSG:28992) verwacht", strict)

    epsg = gdf.crs.to_epsg()
    if epsg != RD_EPSG:
        return _fail(
            f"CRS is EPSG:{epsg}, verwacht EPSG:{RD_EPSG} (RD-stelsel)", strict
        )

    if check_bounds and not gdf.empty:
        minx, miny, maxx, maxy = gdf.total_bounds
        rmin_x, rmin_y, rmax_x, rmax_y = RD_PLAUSIBLE_BOUNDS
        if not (rmin_x <= minx and miny >= rmin_y and maxx <= rmax_x and maxy <= rmax_y):
            return _fail(
                f"BBOX {(minx, miny, maxx, maxy)} valt buiten plausibel "
                f"RD-bereik {RD_PLAUSIBLE_BOUNDS} — controleer of CRS-label correct is",
                strict,
            )

    return True


def _fail(msg: str, strict: bool) -> bool:
    if strict:
        raise CRSValidationError(msg)
    return False


def http_session(
    *,
    total_retries: int = 5,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    """Geef een ``requests.Session`` met retry-logica voor PDOK."""
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "geo_stack/0.2 (NL geospatial automation)"})
    return session


def validate_bbox(bbox: BBox, *, must_be_rd: bool = True) -> BBox:
    """Valideer formaat (en optioneel RD-bereik) van een BBOX."""
    if len(bbox) != 4:
        raise ValueError(f"BBOX moet 4 waarden hebben, kreeg {len(bbox)}: {bbox}")
    minx, miny, maxx, maxy = bbox
    if minx >= maxx or miny >= maxy:
        raise ValueError(
            f"BBOX-volgorde is (minx, miny, maxx, maxy); "
            f"kreeg ongeldige coördinaten {bbox}"
        )
    if must_be_rd:
        rmin_x, rmin_y, rmax_x, rmax_y = RD_PLAUSIBLE_BOUNDS
        if minx < rmin_x or maxx > rmax_x or miny < rmin_y or maxy > rmax_y:
            raise ValueError(
                f"BBOX {bbox} buiten plausibel RD-stelsel-bereik "
                f"{RD_PLAUSIBLE_BOUNDS}; controleer of coördinaten in EPSG:28992 staan"
            )
    return bbox


def hash_bbox(bbox: BBox, length: int = 10) -> str:
    """Deterministische korte hash voor gebruik in cache-bestandsnamen."""
    canonical = ",".join(f"{c:.3f}" for c in bbox)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:length]
