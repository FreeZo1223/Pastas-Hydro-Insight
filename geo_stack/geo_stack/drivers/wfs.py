"""Generieke WFS 2.0 driver voor geo_stack.

Leest endpoint, typename, default_crs en cql_filter uit de YAML-entry.
Pagineert automatisch via startIndex + count=5000.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd

from geo_stack.core.geo_utils import BBox, http_session
from geo_stack.drivers.base import BaseDriver

log = logging.getLogger(__name__)

_WFS_PAGE_SIZE = 5000


class WFSDriver(BaseDriver):
    """Generieke WFS 2.0 GetFeature driver met automatische paginatie.

    Leest de volgende velden uit ``self.entry``:
    - ``endpoint``: WFS service URL
    - ``typename`` / ``typeName``: default feature type
    - ``default_crs``: default ``"EPSG:28992"``
    - ``cql_filter``: ``false`` = gebruik alleen BBOX, geen CQL-filter
    """

    def fetch(self, bbox: BBox, **kw: Any) -> gpd.GeoDataFrame:
        """Haal WFS-features op binnen ``bbox`` via paginatie.

        Parameters
        ----------
        bbox
            ``(minx, miny, maxx, maxy)`` in EPSG:28992.
        **kw
            Optionele override: ``feature_type`` overschrijft de typename uit entry.

        Returns
        -------
        gpd.GeoDataFrame
            Features in EPSG:28992.
        """
        endpoint: str = self.entry["endpoint"]
        typename: str = (
            kw.pop("feature_type", None)
            or self.entry.get("typename")
            or self.entry.get("typeName")
        )
        if not typename:
            raise ValueError(
                f"WFSDriver: geen typename gevonden in entry en geen feature_type kwarg. "
                f"Entry: {self.entry.get('label', '?')}"
            )

        # cql_filter in de entry is informatief: deze driver filtert uitsluitend
        # op BBOX (server-side) — nooit via CQL_FILTER, omdat diverse PDOK-WFS
        # tile-cached zijn en CQL stil negeren. Filter attributen client-side.
        srs = self.entry.get("default_crs", "EPSG:28992")
        minx, miny, maxx, maxy = bbox

        session = http_session()
        frames: list[gpd.GeoDataFrame] = []
        offset = 0

        while True:
            params: dict[str, Any] = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": typename,
                "outputFormat": "application/json",
                "srsName": srs,
                "BBOX": f"{minx},{miny},{maxx},{maxy},{srs}",
                "count": _WFS_PAGE_SIZE,
                "startIndex": offset,
            }

            log.debug(
                "WFS GetFeature: %s / %s offset=%d", endpoint, typename, offset
            )
            resp = session.get(endpoint, params=params, timeout=60)
            resp.raise_for_status()

            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"WFSDriver: respons is geen JSON voor {typename} "
                    f"(controleer outputFormat-ondersteuning): {exc}"
                ) from exc

            features = data.get("features", [])
            n = len(features)
            if n == 0:
                break

            frames.append(gpd.GeoDataFrame.from_features(features, crs=srs))

            if n < _WFS_PAGE_SIZE:
                break
            offset += _WFS_PAGE_SIZE

        if not frames:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

        gdf_out = gpd.GeoDataFrame(
            gpd.pd.concat(frames, ignore_index=True), crs=srs
        )
        if gdf_out.crs and gdf_out.crs.to_epsg() != 28992:
            gdf_out = gdf_out.to_crs("EPSG:28992")
        return gdf_out
