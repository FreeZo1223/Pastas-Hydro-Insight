"""Cloud-native driver — wrapper voor bestaande cloud_native skills.

Delegeert naar ``geo_stack.skills.cloud_native.stream_3dbag`` of
``stream_bag_extract`` op basis van de URL in de YAML-entry.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd

from geo_stack.core.geo_utils import BBox
from geo_stack.drivers.base import BaseDriver

log = logging.getLogger(__name__)


class CloudNativeDriver(BaseDriver):
    """Wrapper-driver voor cloud-native DuckDB-streaming skills.

    Leest de volgende velden uit ``self.entry``:
    - ``cloud_native_url``: remote URL naar GPKG-ZIP of GeoPackage
    - ``internal_file``: bestandsnaam binnen ZIP (voor 3DBAG)
    - ``layers``: lijst van beschikbare lagen (eerste laag als default)

    Kiest automatisch de juiste skill op basis van de URL:
    - ``3dbag.nl`` → ``stream_3dbag``
    - anders → ``stream_bag_extract``
    """

    def fetch(self, bbox: BBox, **kw: Any) -> gpd.GeoDataFrame:
        """Haal cloud-native features op via DuckDB-streaming.

        Parameters
        ----------
        bbox
            ``(minx, miny, maxx, maxy)`` in EPSG:28992.
        **kw
            ``layer``: laagnaam (overrideert default uit entry).

        Returns
        -------
        gpd.GeoDataFrame
            Features in EPSG:28992.
        """
        url: str = self.entry.get("cloud_native_url", "")
        internal_file: str | None = self.entry.get("internal_file")
        layers: list[str] = self.entry.get("layers", [])
        default_layer: str = layers[0] if layers else "pand"
        layer: str = kw.pop("layer", default_layer)

        if "3dbag.nl" in url:
            from geo_stack.skills.cloud_native import stream_3dbag

            stream_kwargs: dict[str, Any] = {"bbox": bbox, "layer": layer}
            if url:
                stream_kwargs["url"] = url
            if internal_file:
                stream_kwargs["internal_gpkg"] = internal_file
            log.info(
                "CloudNativeDriver: 3DBAG stream via %s (layer=%s)", url, layer
            )
            return stream_3dbag(**stream_kwargs, **kw)
        else:
            from geo_stack.skills.cloud_native import stream_bag_extract

            extract_kwargs: dict[str, Any] = {"bbox": bbox, "object_type": layer}
            if url:
                extract_kwargs["url"] = url
            log.info(
                "CloudNativeDriver: BAG extract stream via %s (layer=%s)", url, layer
            )
            return stream_bag_extract(**extract_kwargs, **kw)
