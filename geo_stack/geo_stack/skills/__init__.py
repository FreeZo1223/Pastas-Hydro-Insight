"""geo_stack.skills — datasource-specifieke fetch-functies.

Beschikbare skills:
    besi_fetcher      — BeSI Beschermde Soorten Indicator (kansenkaarten 2025)
    bgt               — BGT WFS
    ahn               — AHN4 WCS
    kadaster          — PDOK Locatieserver percelen (kadastrale aanduidingen)
    locatieserver     — PDOK Locatieserver generieke geocoding (adres/plaats/...)
    bro_grondwater    — BRO grondwaterspiegeldiepte raster (GHG/GLG/GVG) + peilbuizen
    landschapsleutel  — FGR-regio + BRO bodemtype: benadering van de Landschapssleutel
    cloud_native      — 3DBAG / BAG via DuckDB streaming
    ndvi_stac         — Sentinel-2 NDVI via STAC
    gee               — Google Earth Engine
    knmi              — KNMI Data Platform
    bro.bodemkaart    — BRO Bodemkaart WFS
    bro.peilbuizen    — BRO Peilbuizen REST
"""
