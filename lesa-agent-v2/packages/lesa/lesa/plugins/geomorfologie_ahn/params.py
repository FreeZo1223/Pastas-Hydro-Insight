"""Parameters voor geomorfologie_ahn."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lesa.plugins._base import PluginParams


class GeomorfologieAhnParams(PluginParams):
    """Parameters voor de AHN4 reliëfanalyse."""

    resolution: float = Field(
        default=5.0,
        description=(
            "Pixelgrootte in meter: 0.5 (detail) of 5.0 (overview). "
            "Gebruik 5.0 voor schaalniveau 1-2, 0.5 voor niveau 3. "
            "Bij 'auto' of 'cog' fetch_method geen grootte-beperking bij 0.5m."
        ),
    )
    product: str = Field(
        default="DTM",
        description="AHN-product: 'DTM' (kaal maaiveld, aanbevolen) of 'DSM' (inclusief bebouwing).",
    )
    laagte_percentiel: float = Field(
        default=25.0,
        ge=5.0,
        le=50.0,
        description="Hoogte-percentiel als grens voor 'laagtegebied' (default P25).",
    )
    aoi_buffer_m: float = Field(
        default=250.0,
        ge=0.0,
        le=2000.0,
        description=(
            "Buffer in meters rondom AOI voor ophalen AHN (voorkomt randeffecten). "
            "Bij WCS-modus wordt de buffer automatisch geclipped als de totale "
            "tile de 5km-kantlengte-limiet overschrijdt."
        ),
    )
    fetch_method: Literal["auto", "wcs", "cog"] = Field(
        default="auto",
        description=(
            "'auto' schakelt naar COG als de AOI groter is dan ~25 Mpx bij doelresolutie "
            "of een kant > 5 km. 'wcs' dwingt WCS (geeft fout bij te grote AOI bij 0.5m). "
            "'cog' gebruikt altijd cloud-native rasterio /vsicurl/ via PDOK OGC API."
        ),
    )
