"""OGC API Features driver voor geo_stack.

Ondersteunt PDOK OGC API-endpoints zoals de BGT OGC API.
Pagineert via de ``next``-link in de respons.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd

from geo_stack.core.geo_utils import BBox, http_session
from geo_stack.drivers.base import BaseDriver

log = logging.getLogger(__name__)

_OGC_CRS_28992 = "http://www.opengis.net/def/crs/EPSG/0/28992"
_OGC_PAGE_SIZE = 1000


class OGCAPIDriver(BaseDriver):
    """OGC API Features driver (PDOK OGC API-endpoints).

    Leest de volgende velden uit ``self.entry``:
    - ``endpoint``: basis-URL van de OGC API service
    - ``default_crs``: default ``"EPSG:28992"``

    Verwacht ``feature_type`` of ``collection`` als kwarg om de collection te selecteren.
    """

    def fetch(self, bbox: BBox, **kw: Any) -> gpd.GeoDataFrame:
        """Haal OGC API Features op binnen ``bbox``.

        Parameters
        ----------
        bbox
            ``(minx, miny, maxx, maxy)`` in EPSG:28992.
        **kw
            ``feature_type`` of ``collection``: de collection-naam in de OGC API.

        Returns
        -------
        gpd.GeoDataFrame
            Features in EPSG:28992.

        Raises
        ------
        ValueError
            Als geen collection opgegeven is.
        """
        endpoint: str = self.entry["endpoint"].rstrip("/")
        collection: str = kw.pop("feature_type", None) or kw.pop("collection", None)
        if not collection:
            raise ValueError(
                f"OGCAPIDriver: geef feature_type of collection op als kwarg. "
                f"Entry: {self.entry.get('label', '?')}"
            )

        srs = self.entry.get("default_crs", "EPSG:28992")
        minx, miny, maxx, maxy = bbox
        items_url = f"{endpoint}/collections/{collection}/items"

        session = http_session()
        frames: list[gpd.GeoDataFrame] = []

        params: dict[str, Any] = {
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "bbox-crs": _OGC_CRS_28992,
            "crs": _OGC_CRS_28992,
            "limit": _OGC_PAGE_SIZE,
            "f": "json",
        }

        url: str | None = items_url
        while url:
            log.debug("OGC API Features: GET %s", url)
            if url == items_url:
                resp = session.get(url, params=params, timeout=60)
            else:
                # Volgende pagina via next-link (bevat al alle params)
                resp = session.get(url, timeout=60)
            resp.raise_for_status()

            data = resp.json()
            features = data.get("features", [])
            if not features:
                break

            frames.append(gpd.GeoDataFrame.from_features(features, crs=srs))

            # Zoek next-link voor paginatie
            url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    url = link.get("href")
                    break

        if not frames:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

        gdf_out = gpd.GeoDataFrame(
            gpd.pd.concat(frames, ignore_index=True), crs=srs
        )
        if gdf_out.crs and gdf_out.crs.to_epsg() != 28992:
            gdf_out = gdf_out.to_crs("EPSG:28992")
        return gdf_out
