"""bro_grondwater — BRO grondwaterspiegeldiepte (raster) + peilbuizen (punt).

Twee BRO-grondwaterproducten in één skill:

1. **Grondwaterspiegeldiepte** — geïnterpoleerde GHG/GLG/GVG-rasters (cm onder
   maaiveld), TNO/Stowa-product op basis van peilbuismetingen. Service: PDOK WCS
   (niet WMS — WMS is alleen visualisatie). Output: GeoTIFF EPSG:28992.

2. **Peilbuizen (GMW)** — meetlocaties met maaiveld, filterdiepte, status. Bron:
   BRO publieke REST API (de oude PDOK WFS is eind 2025 uitgezet). Output:
   GeoDataFrame EPSG:28992. Voor de tijdreeks per filter: zie
   :func:`geo_stack.skills.bro.peilbuizen.fetch_gld_timeseries`.

Functies:
    fetch_grondwaterstand(bbox, product="GHG", ...) -> Path
    fetch_peilbuizen(bbox, ...) -> GeoDataFrame

Uncertainty visibility:
    - De grondwaterspiegeldiepte is **geïnterpoleerd** uit puntmetingen.
      In gebieden zonder dichtbij gelegen peilbuizen is de onzekerheid hoger.
      Combineer altijd het raster met de peilbuispunten om de dichtheid van
      ondersteunende metingen zichtbaar te maken.
    - Peilbuizen met ``tube_status != "gebruiksklaar"`` zijn niet betrouwbaar.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from geo_stack.core.geo_utils import BBox, hash_bbox, http_session, validate_bbox
from geo_stack.skills.bro.peilbuizen import (
    BRO_GLD_REST_BASE,
    fetch_peilbuizen as _fetch_peilbuizen_rest,
)

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints + producten
# ---------------------------------------------------------------------------

GRONDWATERSPIEGELDIEPTE_WCS = (
    "https://service.pdok.nl/bzk/bro-grondwaterspiegeldiepte/wcs/v1_0"
)
GMW_DETAIL_URL_TEMPLATE = "https://publiek.broservices.nl/gm/gmw/v1/objects/{bro_id}"

# WCS coverage-IDs per product. PDOK kan deze hernoemen — als de service een
# 404/Onbekende-coverage gooit, override via parameter ``coverage_id``.
WCS_COVERAGE_BY_PRODUCT: dict[str, str] = {
    "GHG": "GHG",
    "GLG": "GLG",
    "GVG": "GVG",
}

VALID_PRODUCTS: frozenset[str] = frozenset(WCS_COVERAGE_BY_PRODUCT)

DEFAULT_RESOLUTION_M = 25.0


class GrondwaterFetchError(RuntimeError):
    """Fout bij ophalen van BRO grondwaterdata (raster of peilbuizen)."""


# ---------------------------------------------------------------------------
# Publieke API
# ---------------------------------------------------------------------------


def fetch_grondwaterstand(
    bbox: BBox,
    product: str = "GHG",
    *,
    resolution_m: float = DEFAULT_RESOLUTION_M,
    output_path: Path | str | None = None,
    coverage_id: str | None = None,
    endpoint: str = GRONDWATERSPIEGELDIEPTE_WCS,
) -> Path:
    """Download BRO grondwaterspiegeldiepte als GeoTIFF voor een BBOX.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    product
        ``"GHG"`` (Gemiddelde Hoogste Grondwaterstand),
        ``"GLG"`` (Gemiddelde Laagste Grondwaterstand) of
        ``"GVG"`` (Gemiddelde Voorjaarsgrondwaterstand).
        Waarden in cm onder maaiveld.
    resolution_m
        Pixelgrootte in meters. Default 25 m. Lager = scherper + groter bestand.
    output_path
        Pad voor de GeoTIFF. Default: ``cwd/grondwater_<product>_<bbox-hash>.tif``.
    coverage_id
        Override voor de WCS-coverage naam. Gebruik als PDOK de naamgeving
        wijzigt. Default: ``WCS_COVERAGE_BY_PRODUCT[product]``.
    endpoint
        WCS-endpoint URL. Default: PDOK BRO grondwaterspiegeldiepte.

    Returns
    -------
    pathlib.Path
        Pad naar de gedownloade GeoTIFF (EPSG:28992).

    Raises
    ------
    GrondwaterFetchError
        Ongeldig product, ongeldig bbox, of HTTP/parse-fout.

    Notes
    -----
    Het raster is **geïnterpoleerd** uit BRO-peilbuismetingen. In gebieden
    zonder dichtbij gelegen peilbuizen is de onzekerheid groter. Combineer met
    :func:`fetch_peilbuizen` om de meetdichtheid zichtbaar te maken.
    """
    if product not in VALID_PRODUCTS:
        raise GrondwaterFetchError(
            f"product moet één van {sorted(VALID_PRODUCTS)} zijn, kreeg {product!r}"
        )
    validate_bbox(bbox, must_be_rd=True)

    coverage = coverage_id or WCS_COVERAGE_BY_PRODUCT[product]
    minx, miny, maxx, maxy = bbox
    width_m, height_m = maxx - minx, maxy - miny

    if width_m <= 0 or height_m <= 0:
        raise GrondwaterFetchError(f"BBOX heeft geen oppervlakte: {bbox}")

    width_px = max(1, int(round(width_m / resolution_m)))
    height_px = max(1, int(round(height_m / resolution_m)))

    if output_path is None:
        bb_hash = hash_bbox(bbox)
        output_path = Path.cwd() / f"grondwater_{product.lower()}_{bb_hash}.tif"
    else:
        output_path = Path(output_path)

    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": coverage,
        "format": "image/tiff",
        "subsettingCRS": "http://www.opengis.net/def/crs/EPSG/0/28992",
        "outputCRS": "http://www.opengis.net/def/crs/EPSG/0/28992",
        "subset": [f"X({minx},{maxx})", f"Y({miny},{maxy})"],
        "scaleSize": f"X({width_px}),Y({height_px})",
    }

    session = http_session()
    log.info(
        "WCS GetCoverage %s @ %s (%dx%d px, %.0f m res)",
        coverage, bbox, width_px, height_px, resolution_m,
    )

    try:
        resp = session.get(endpoint, params=params, timeout=300, stream=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise GrondwaterFetchError(
            f"WCS fetch mislukt voor {coverage} @ {endpoint}: {exc}"
        ) from exc

    content_type = resp.headers.get("Content-Type", "")
    if "tiff" not in content_type.lower():
        raise GrondwaterFetchError(
            f"Onverwachte Content-Type {content_type!r}; eerste 256 bytes: "
            f"{resp.content[:256]!r}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)

    _stamp_metadata(output_path, product=product, coverage=coverage, bbox=bbox)
    log.info("Grondwater raster opgeslagen: %s", output_path)
    return output_path


def fetch_peilbuizen(
    bbox: BBox,
    *,
    output_path: Path | str | None = None,
    extra_buffer_m: float = 500.0,
    timeout_s: float = 60.0,
) -> "gpd.GeoDataFrame":
    """Haal BRO peilbuizen (GMW) op binnen ``bbox`` + buffer.

    Thin wrapper rond :func:`geo_stack.skills.bro.peilbuizen.fetch_peilbuizen`
    die twee extra kolommen toevoegt voor downstream gebruik:

    - ``gmw_detail_url`` — REST-endpoint voor volledige GMW-details (filters,
      GLD-koppelingen).
    - ``gld_base_url`` — basis-URL voor de GLD REST API; combineer met een
      GLD-id (uit de detail-call) om de tijdreeks op te halen.

    Returns
    -------
    geopandas.GeoDataFrame
        EPSG:28992, met kolommen:
        ``bro_id, well_code, ground_level_m_nap, construction_date,
        n_monitoring_tubes, initial_function, tube_status,
        screen_top_m_nap, screen_bottom_m_nap, gmw_detail_url,
        gld_base_url, geometry``.

        Lege GeoDataFrame als geen peilbuizen in BBOX.

    Raises
    ------
    GrondwaterFetchError
        Bij netwerk- of parse-fout (wrapt de onderliggende ``BROFetchError``).

    Notes
    -----
    De directe peilbuis-WFS van PDOK is eind 2025 uitgezet. Deze functie
    gebruikt de BRO publieke REST API (POST + JSON, XML-respons).
    Tijdreeksen zelf worden niet door deze functie opgehaald — gebruik
    :func:`geo_stack.skills.bro.peilbuizen.fetch_gld_timeseries(gld_id)`
    nadat je via ``gmw_detail_url`` de GLD-id's hebt gevonden.
    """
    from geo_stack.skills.bro.peilbuizen import BROFetchError

    try:
        gdf = _fetch_peilbuizen_rest(
            bbox,
            output_path=output_path,
            extra_buffer_m=extra_buffer_m,
            timeout_s=timeout_s,
        )
    except BROFetchError as exc:
        raise GrondwaterFetchError(str(exc)) from exc

    if gdf.empty:
        return gdf

    if "bro_id" in gdf.columns:
        gdf = gdf.assign(
            gmw_detail_url=gdf["bro_id"].apply(
                lambda b: GMW_DETAIL_URL_TEMPLATE.format(bro_id=b) if b else None
            ),
            gld_base_url=BRO_GLD_REST_BASE,
        )
    return gdf


# ---------------------------------------------------------------------------
# Privé helpers
# ---------------------------------------------------------------------------


def _stamp_metadata(
    path: Path, *, product: str, coverage: str, bbox: BBox
) -> None:
    """Schrijf product/bbox-metadata als GeoTIFF tags. Niet-fataal bij missende rasterio."""
    try:
        import rasterio
    except ImportError:
        log.warning("rasterio niet geïnstalleerd; metadata-stamp overgeslagen")
        return

    try:
        with rasterio.open(path, "r+") as ds:
            ds.update_tags(
                PRODUCT=product,
                COVERAGE=coverage,
                SOURCE="BRO grondwaterspiegeldiepte (PDOK WCS)",
                BBOX=",".join(str(c) for c in bbox),
            )
    except Exception as exc:
        log.warning("GeoTIFF metadata-stamp mislukt voor %s: %s", path, exc)
