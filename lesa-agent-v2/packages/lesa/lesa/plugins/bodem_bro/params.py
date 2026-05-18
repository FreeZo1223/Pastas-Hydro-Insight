"""Parameters voor bodem_bro."""

from __future__ import annotations

from pydantic import Field

from lesa.plugins._base import PluginParams


class BodemBroParams(PluginParams):
    """Parameters voor BRO Bodemkaart fetch."""

    aoi_buffer_m: float = Field(
        default=200.0,
        ge=0.0,
        le=2000.0,
        description="Buffer rondom AOI in meters (bodemvlakken kunnen de grens overspannen).",
    )
    min_vlak_ha: float = Field(
        default=0.1,
        ge=0.01,
        description="Minimale oppervlakte (ha) voor rapportage van een bodemtype.",
    )
