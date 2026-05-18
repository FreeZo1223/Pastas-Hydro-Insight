"""BRO — Basisregistratie Ondergrond skills.

Submodules:
    bodemkaart   — Bodemkaart 1:50.000 (vlakken, classificaties)
    peilbuizen   — Grondwatermonitoringputten (GMW) + tijdreeksen (GLD)

Re-exports voor backwards compatibility met de pre-split API
(``from geo_stack.skills.bro import fetch_bodemkaart``).
"""

from geo_stack.skills.bro.bodemkaart import (
    BODEMKAART_ENDPOINT,
    BODEMKAART_TYPENAME,
    BROFetchError,
    fetch_bodemkaart,
    get_bro_capabilities,
)
from geo_stack.skills.bro.peilbuizen import (
    BRO_GLD_REST_BASE,
    BRO_GMW_SEARCH_URL,
    fetch_peilbuizen,
    fetch_gld_timeseries,
    parse_bro_csv,
    parse_dino_csv,
)

__all__ = [
    "BODEMKAART_ENDPOINT",
    "BODEMKAART_TYPENAME",
    "BROFetchError",
    "BRO_GLD_REST_BASE",
    "BRO_GMW_SEARCH_URL",
    "fetch_bodemkaart",
    "fetch_gld_timeseries",
    "fetch_peilbuizen",
    "get_bro_capabilities",
    "parse_bro_csv",
    "parse_dino_csv",
]
