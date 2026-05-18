"""landschapsleutel — FGR + BRO bodemtype: benadering van de Landschapssleutel.

Combineert twee publieke GIS-bronnen:
  1. FGR (Fysisch-Geografische Regio's) via PDOK WFS — grootschalige
     landschapstypen (RVO/Alterra, ~10 regio's voor heel Nederland).
  2. BRO Bodemkaart 1:50.000 via WUR/BIS geoserver — bodemtype + grondwatertrap.

Resultaat: bodemkaartvlakken verrijkt met de FGR-regio waarbinnen ze vallen.

⚠️ Benadering: de volledige WUR Landschapssleutel (2014) integreert naast
FGR-regio en bodemtype ook reliëf, hydrologische context en historisch
landgebruik. Deze module levert een indicatieve eerste schets op basis van
twee publiek beschikbare datasources. Gebruik voor definitieve LESA/habitaat-
analyses de volledige Landschapssleutel of raadpleeg een ecoloog.

Functies:
    classify_landscape(bbox, ...) -> GeoDataFrame
        Kolommen: fgr_regio, fgr_sectie, fgr_serie, bodemtype, gt_klasse
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from geo_stack.core.geo_utils import BBox, validate_bbox
from geo_stack.skills.bro.bodemkaart import BROFetchError, fetch_bodemkaart

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints + schema-constanten
# ---------------------------------------------------------------------------

FGR_WFS_ENDPOINT = "https://service.pdok.nl/rvo/fgr/wfs/v1_0"
FGR_TYPENAME = "fgr:FysischGeografischeRegio"

# Prioriteitslijst van mogelijke FGR-kolomnamen per uitvoerveld.
# De eerste naam die in de WFS-respons bestaat wint.
_FGR_REGIO_CANDIDATES = ("naam", "fgr_naam", "regio", "fgrnaam", "NAME", "NAAM")
_FGR_SECTIE_CANDIDATES = ("sectie", "fgr_sectie", "SECTIE")
_FGR_SERIE_CANDIDATES = ("serie", "fgr_serie", "SERIE")

# Idem voor bodemkaart.
_BODEM_TYPE_CANDIDATES = (
    "bodemtype", "BktNm", "bktnm", "bodemcode", "BODEMTYPE",
)
_BODEM_GT_CANDIDATES = (
    "gt_klasse", "gt", "Gt", "GT", "grondwatertrap", "GT_KLASSE",
)

OUTPUT_COLUMNS = ("fgr_regio", "fgr_sectie", "fgr_serie", "bodemtype", "gt_klasse")


class LandschapsclassificatieFetchError(RuntimeError):
    """Fout bij ophalen of combineren van FGR/bodemkaart voor classify_landscape."""


# ---------------------------------------------------------------------------
# Publieke API
# ---------------------------------------------------------------------------


def classify_landscape(
    bbox: BBox,
    *,
    fgr_endpoint: str = FGR_WFS_ENDPOINT,
    fgr_typename: str = FGR_TYPENAME,
    extra_buffer_m: float = 200.0,
    output_path: Path | str | None = None,
) -> "gpd.GeoDataFrame":
    """Classificeer landschapstype per bodemkaartvlak binnen bbox.

    Haalt FGR-polygonen (grootschalige landschapstypen) en BRO Bodemkaart
    (bodemtype + grondwatertrap) op, en retourneert bodemkaartvlakken verrijkt
    met de FGR-regio waarbinnen ze vallen.

    Parameters
    ----------
    bbox
        ``(minx, miny, maxx, maxy)`` in EPSG:28992.
    fgr_endpoint
        WFS-endpoint voor de FGR. Default: PDOK RVO FGR WFS.
    fgr_typename
        WFS typename voor FGR. Default: ``fgr:FysischGeografischeRegio``.
    extra_buffer_m
        Buffer rondom bbox in meters; polygonen kunnen grenzen overspannen.
    output_path
        Optioneel pad om resultaat als GeoPackage op te slaan.

    Returns
    -------
    geopandas.GeoDataFrame
        Bodemkaartvlakken in EPSG:28992 met kolommen:
        ``fgr_regio, fgr_sectie, fgr_serie, bodemtype, gt_klasse, geometry``.
        Lege GeoDataFrame als geen features in BBOX.

    Raises
    ------
    LandschapsclassificatieFetchError
        Bij netwerk-, parse- of joinfouten.

    Notes
    -----
    Bodemkaartvlakken die op de grens van twee FGR-regio's liggen krijgen de
    regio van de eerste intersectie. Dit is een bekende beperking van de
    benadering.
    """
    validate_bbox(bbox, must_be_rd=True)

    try:
        fgr_gdf = _fetch_fgr(bbox, fgr_endpoint, fgr_typename, extra_buffer_m)
    except LandschapsclassificatieFetchError:
        raise
    except Exception as exc:
        raise LandschapsclassificatieFetchError(
            f"FGR fetch mislukt voor {fgr_typename} @ {fgr_endpoint}: {exc}"
        ) from exc

    try:
        bodem_gdf = fetch_bodemkaart(bbox, extra_buffer_m=extra_buffer_m)
    except BROFetchError as exc:
        raise LandschapsclassificatieFetchError(str(exc)) from exc

    if fgr_gdf.empty or bodem_gdf.empty:
        log.warning(
            "Geen FGR (%d) of bodemkaart (%d) features voor bbox %s — lege GDF",
            len(fgr_gdf), len(bodem_gdf), bbox,
        )
        return _empty_result()

    result = _join_and_normalise(fgr_gdf, bodem_gdf)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        result.to_file(out, driver="GPKG")
        log.info(
            "Landschapsclassificatie opgeslagen: %s (%d features)", out, len(result)
        )

    return result


# ---------------------------------------------------------------------------
# Privé helpers
# ---------------------------------------------------------------------------


def _fetch_fgr(
    bbox: BBox,
    endpoint: str,
    typename: str,
    extra_buffer_m: float,
) -> "gpd.GeoDataFrame":
    """Haal FGR-polygonen op via WFS."""
    import geopandas as gpd

    minx, miny, maxx, maxy = bbox
    b = extra_buffer_m
    buf_bbox = (minx - b, miny - b, maxx + b, maxy + b)

    wfs_url = (
        f"{endpoint}?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeName={typename}&srsName=EPSG:28992"
        f"&bbox={buf_bbox[0]},{buf_bbox[1]},{buf_bbox[2]},{buf_bbox[3]},EPSG:28992"
        f"&outputFormat=application/json"
    )
    log.info("FGR fetch: %s @ %s", typename, buf_bbox)

    try:
        gdf = gpd.read_file(wfs_url, engine="pyogrio")
    except Exception as exc:
        raise LandschapsclassificatieFetchError(
            f"FGR WFS fetch mislukt ({typename}): {exc}"
        ) from exc

    if gdf.empty:
        return gdf
    if gdf.crs is None or gdf.crs.to_epsg() != 28992:
        gdf = gdf.to_crs("EPSG:28992")
    return gdf


def _join_and_normalise(
    fgr_gdf: "gpd.GeoDataFrame",
    bodem_gdf: "gpd.GeoDataFrame",
) -> "gpd.GeoDataFrame":
    """Spatial join bodemkaart × FGR, hernoem kolommen, retourneer output GDF."""
    # Hernoem FGR-kolommen naar standaardnamen vóór de join
    fgr_renamed = _rename_fgr_columns(fgr_gdf)

    fgr_cols = [c for c in ("fgr_regio", "fgr_sectie", "fgr_serie", "geometry")
                if c in fgr_renamed.columns]
    fgr_small = fgr_renamed[fgr_cols]

    # Spatial join: elke bodemkaartvlak krijgt de FGR-regio waar hij (hoofd-
    # zakelijk) in valt. Bij randoverlap: eerste match (voldoende voor benadering).
    joined = bodem_gdf.sjoin(fgr_small, how="left", predicate="intersects")

    # Verwijder dubbele rijen bij bodemvlakken op FGR-grenzen
    if joined.index.duplicated().any():
        joined = joined[~joined.index.duplicated(keep="first")]

    # Hernoem bodemkaart-kolommen
    joined = _rename_bodem_columns(joined)

    # Zorg dat alle uitvoerkolommen bestaan
    for col in OUTPUT_COLUMNS:
        if col not in joined.columns:
            joined = joined.assign(**{col: None})

    result = joined[list(OUTPUT_COLUMNS) + ["geometry"]].copy()

    if result.crs is None or result.crs.to_epsg() != 28992:
        result = result.set_crs("EPSG:28992", allow_override=True)

    return result


def _first_match(columns: "gpd.Index", candidates: tuple[str, ...]) -> str | None:
    """Geef de eerste kolomnaam uit candidates die in columns bestaat."""
    for name in candidates:
        if name in columns:
            return name
    return None


def _rename_fgr_columns(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    col_map: dict[str, str] = {}
    regio_src = _first_match(gdf.columns, _FGR_REGIO_CANDIDATES)
    if regio_src:
        col_map[regio_src] = "fgr_regio"
    sectie_src = _first_match(gdf.columns, _FGR_SECTIE_CANDIDATES)
    if sectie_src and sectie_src not in col_map:
        col_map[sectie_src] = "fgr_sectie"
    serie_src = _first_match(gdf.columns, _FGR_SERIE_CANDIDATES)
    if serie_src and serie_src not in col_map:
        col_map[serie_src] = "fgr_serie"
    return gdf.rename(columns=col_map) if col_map else gdf


def _rename_bodem_columns(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    col_map: dict[str, str] = {}
    bodem_src = _first_match(gdf.columns, _BODEM_TYPE_CANDIDATES)
    if bodem_src:
        col_map[bodem_src] = "bodemtype"
    gt_src = _first_match(gdf.columns, _BODEM_GT_CANDIDATES)
    if gt_src and gt_src not in col_map:
        col_map[gt_src] = "gt_klasse"
    return gdf.rename(columns=col_map) if col_map else gdf


def _empty_result() -> "gpd.GeoDataFrame":
    import geopandas as gpd

    return gpd.GeoDataFrame(
        {col: [] for col in OUTPUT_COLUMNS},
        geometry=[],
        crs="EPSG:28992",
    )
