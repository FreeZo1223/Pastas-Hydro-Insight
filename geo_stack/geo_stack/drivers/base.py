"""Abstracte basisklasse voor alle geo_stack protocol-drivers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import geopandas as gpd

from geo_stack.core.geo_utils import BBox

log = logging.getLogger(__name__)


class BaseDriver(ABC):
    """Basisklasse die elke protocol-driver moet implementeren.

    Subklassen (WFSDriver, OGCAPIDriver, CloudNativeDriver) ontvangen
    een ``entry``-dict uit ``data_sources.yaml`` en implementeren ``fetch``.
    """

    def __init__(self, entry: dict) -> None:
        """Initialiseer de driver met een YAML-entry.

        Parameters
        ----------
        entry
            Dictionary met velden uit data_sources.yaml (endpoint, typename, …).
        """
        self.entry = entry

    @abstractmethod
    def fetch(self, bbox: BBox, **kw) -> gpd.GeoDataFrame:
        """Haal features op binnen ``bbox``.

        Parameters
        ----------
        bbox
            ``(minx, miny, maxx, maxy)`` in EPSG:28992.
        **kw
            Extra kwargs doorgegeven vanuit ``fetch_features``.

        Returns
        -------
        gpd.GeoDataFrame
            Features in EPSG:28992.
        """
        ...
