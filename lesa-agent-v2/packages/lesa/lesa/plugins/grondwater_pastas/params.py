"""Parameters voor de grondwater_pastas plugin."""

from __future__ import annotations

from pydantic import Field

from lesa.plugins._base import PluginParams


class GrondwaterPastasParams(PluginParams):
    """Parameters voor BRO-peilbuizen + KNMI + PASTAS-modellering."""

    aoi_buffer_m: float = Field(
        default=500.0,
        ge=0.0,
        le=5000.0,
        description="Buffer rondom AOI om peilbuizen te zoeken (meters).",
    )

    knmi_station: str | None = Field(
        default=None,
        description=(
            "KNMI-klimaatstation-ID (bv. '310' voor Vlissingen). "
            "Leeg = automatisch dichtstbijzijnde klimaatstation."
        ),
    )

    tmin: str = Field(
        default="1990-01-01",
        description="Begin-datum voor KNMI + GLD-reeksen (YYYY-MM-DD).",
    )

    tmax: str | None = Field(
        default=None,
        description="Eind-datum (YYYY-MM-DD); leeg = vandaag.",
    )

    gld_ids: list[str] = Field(
        default_factory=list,
        description=(
            "BRO GLD-identificaties waarvoor tijdreeksen + PASTAS-fits gemaakt "
            "worden (bijv. ['GLD000000073324']). Leeg = alleen punt-inventarisatie."
        ),
    )

    fit_pastas_models: bool = Field(
        default=False,
        description=(
            "True = bouw PASTAS RechargeModel per opgegeven gld_id en rapporteer "
            "NSE/EVP. Vereist [full] extra van pastas-adapter (pastas + pastastore)."
        ),
    )
