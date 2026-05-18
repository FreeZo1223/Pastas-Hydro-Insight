"""BRO Grondwatermonitoring — peilbuizen + tijdreeksen.

Twee BRO-objecten:
- **GMW** (Grondwatermonitoringput): punten met metadata (filterdiepte, NAP-niveau).
  Opgehaald via PDOK WFS (vector punten in EPSG:28992).
- **GLD** (Grondwaterstand Levering): tijdreeks per filter (datum + waterstand m NAP).
  Opgehaald via BRO REST API per GLD-ID; NIET via WFS (alleen punten).

Plus parsers voor lokaal gedownloade CSV-bestanden:
- ``parse_dino_csv``: DINO formaat (header op regel 12, NL-format datum, cm t.o.v. NAP)
- ``parse_bro_csv``: BRO export formaat (header dynamisch te detecteren)

Voor LESA wordt deze skill aangeroepen door de ``grondwater_pastas``-plugin
en de PASTAS-adapter; de skill zelf weet niets van PASTAS.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from geo_stack.core.geo_utils import BBox, validate_bbox
from geo_stack.skills.bro.bodemkaart import BROFetchError

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd

log = logging.getLogger(__name__)

# ── Endpoints ────────────────────────────────────────────────────────────────

# BRO publieke REST API voor GMW-puntenzoekopdrachten en GLD-tijdreeksen.
# PDOK WFS-endpoints voor BRO-grondwater zijn eind 2025 buiten gebruik gesteld.
BRO_GMW_SEARCH_URL = (
    "https://publiek.broservices.nl/gm/gmw/v1/characteristics/searches"
)
BRO_GLD_REST_BASE = "https://publiek.broservices.nl/gm/gld/v1"


# ── REST: peilbuispunten in BBOX ─────────────────────────────────────────────

def fetch_peilbuizen(
    bbox: BBox,
    *,
    output_path: Path | str | None = None,
    endpoint: str = BRO_GMW_SEARCH_URL,
    extra_buffer_m: float = 500.0,
    timeout_s: float = 60.0,
) -> "gpd.GeoDataFrame":
    """Fetch BRO-peilbuispunten (GMW-objecten) in en rondom de BBOX.

    Gebruikt de BRO publieke REST API (POST + JSON body, XML-respons).
    Returnt punten met BRO-id, well-code, maaiveld-NAP en filterdiepte.
    De daadwerkelijke tijdreeks wordt apart opgehaald per GLD-id via
    :func:`fetch_gld_timeseries`.
    """
    import json
    import urllib.request
    import xml.etree.ElementTree as ET

    import geopandas as gpd  # noqa: WPS433
    import pyproj
    from shapely.geometry import Point

    validate_bbox(bbox, must_be_rd=True)
    minx, miny, maxx, maxy = bbox
    b = extra_buffer_m
    buf_rd = (minx - b, miny - b, maxx + b, maxy + b)

    transformer = pyproj.Transformer.from_crs(
        "EPSG:28992", "EPSG:4326", always_xy=True,
    )
    lon_min, lat_min = transformer.transform(buf_rd[0], buf_rd[1])
    lon_max, lat_max = transformer.transform(buf_rd[2], buf_rd[3])

    body = json.dumps({
        "area": {
            "boundingBox": {
                "lowerCorner": {"lat": lat_min, "lon": lon_min},
                "upperCorner": {"lat": lat_max, "lon": lon_max},
            },
        },
    }).encode("utf-8")

    log.info("BRO GMW REST search: bbox_rd=%s, bbox_wgs84=(%.4f,%.4f,%.4f,%.4f)",
             buf_rd, lon_min, lat_min, lon_max, lat_max)

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/xml"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            xml_bytes = resp.read()
    except Exception as exc:
        raise BROFetchError(f"BRO GMW REST fetch mislukt: {exc}") from exc

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise BROFetchError(f"BRO GMW REST: XML parse error: {exc}") from exc

    rows = list(_iter_gmw_documents(root))

    if not rows:
        log.warning("BRO peilbuizen: geen GMW-objecten voor bbox %s", buf_rd)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")

    gdf = gpd.GeoDataFrame(
        rows,
        geometry=[Point(r.pop("_x_rd"), r.pop("_y_rd")) for r in rows],
        crs="EPSG:28992",
    )

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(out, driver="GPKG")
        log.info("Peilbuizen opgeslagen: %s (%d features)", out, len(gdf))

    return gdf


def _iter_gmw_documents(root: "ET.Element"):
    """Iterate over GMW_C blocks and yield property dicts (with _x_rd/_y_rd)."""
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag != "GMW_C":
            continue
        props = _parse_gmw_block(elem)
        if props is not None:
            yield props


def _parse_gmw_block(gmw: "ET.Element") -> dict | None:
    """Extract relevant fields from one GMW_C XML element."""
    bro_id = _first_text(gmw, "broId")
    well_code = _first_text(gmw, "wellCode")
    ground_level = _first_float(gmw, "groundLevelPosition")
    construction_date = _first_text(gmw, "date")
    n_tubes = _first_int(gmw, "numberOfMonitoringTubes")
    initial_function = _first_text(gmw, "initialFunction")
    tube_status = _first_text(gmw, "tubeStatus")
    screen_top = _first_float(gmw, "shallowestScreenTopPosition")
    screen_bottom = _first_float(gmw, "deepestScreenBottomPosition")

    x_rd, y_rd = _delivered_location_rd(gmw)
    if x_rd is None or y_rd is None:
        return None

    return {
        "bro_id": bro_id,
        "well_code": well_code,
        "ground_level_m_nap": ground_level,
        "construction_date": construction_date,
        "n_monitoring_tubes": n_tubes,
        "initial_function": initial_function,
        "tube_status": tube_status,
        "screen_top_m_nap": screen_top,
        "screen_bottom_m_nap": screen_bottom,
        "_x_rd": x_rd,
        "_y_rd": y_rd,
    }


def _first_text(elem: "ET.Element", local_name: str) -> str | None:
    for child in elem.iter():
        if child.tag.rsplit("}", 1)[-1] == local_name and child.text:
            return child.text.strip()
    return None


def _first_float(elem: "ET.Element", local_name: str) -> float | None:
    text = _first_text(elem, local_name)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_int(elem: "ET.Element", local_name: str) -> int | None:
    text = _first_text(elem, local_name)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _delivered_location_rd(gmw: "ET.Element") -> tuple[float | None, float | None]:
    """Find deliveredLocation in EPSG:28992 and return (x, y)."""
    for elem in gmw.iter():
        if elem.tag.rsplit("}", 1)[-1] != "deliveredLocation":
            continue
        srs = elem.attrib.get("srsName", "")
        if "28992" not in srs:
            continue
        for pos in elem.iter():
            if pos.tag.rsplit("}", 1)[-1] != "pos" or not pos.text:
                continue
            parts = pos.text.strip().split()
            if len(parts) >= 2:
                try:
                    return float(parts[0]), float(parts[1])
                except ValueError:
                    return None, None
    return None, None


# ── REST: tijdreeks per GLD-id ───────────────────────────────────────────────

def fetch_groundwater_obs(
    bro_id: str,
    *,
    tube_nr: int | None = None,
    tmin: str | datetime | None = "1900-01-01",
    tmax: str | datetime | None = "2040-01-01",
) -> "pd.DataFrame":
    """Fetch grondwaterstandreeks via hydropandas (BRO-REST).

    Werkt voor zowel **GLD**-id's als **GMW**-id's (laatste vereist ``tube_nr``).
    Hydropandas voegt automatisch metadata toe: ``x``, ``y``, ``ground_level``,
    ``screen_top``, ``screen_bottom``, ``unit`` (m NAP).

    Returns
    -------
    hydropandas.GroundwaterObs
        DataFrame met kolom ``values`` (m NAP). Heeft attributes ``x``, ``y``,
        ``name``, ``ground_level`` etc. voor direct gebruik in PastaStore.
    """
    try:
        import hydropandas as hpd
    except ImportError as exc:
        raise ImportError(
            "hydropandas niet geïnstalleerd; gebruik fetch_gld_timeseries() of "
            "installeer met 'uv add hydropandas'."
        ) from exc

    return hpd.GroundwaterObs.from_bro(
        bro_id=bro_id,
        tube_nr=tube_nr,
        tmin=tmin,
        tmax=tmax,
    )


def fetch_gld_timeseries(
    gld_id: str,
    *,
    tmin: str | datetime | None = None,
    tmax: str | datetime | None = None,
    timeout_s: float = 30.0,
) -> "pd.Series":
    """Fetch grondwaterstandreeks voor één GLD-id via de BRO REST API.

    Parameters
    ----------
    gld_id
        BRO GLD-identificatie (bijv. ``"GLD000000073324"``).
    tmin, tmax
        Optionele datumlimieten als ``"YYYY-MM-DD"`` of ``datetime``.
        Live API geeft meestal de volledige reeks; we filteren client-side.
    timeout_s
        HTTP-timeout in seconden.

    Returns
    -------
    pd.Series
        Index = ``DatetimeIndex`` (genormaliseerd op dag), values =
        waterstand in m NAP (negatief = onder NAP). Naam = gld_id.

    Notes
    -----
    De BRO GLD-endpoint geeft XML/SOAP terug. Voor productiegebruik
    raadt BRO ``hydropandas`` aan. Deze functie biedt een minimale
    standalone-implementatie zonder die dependency.
    """
    import xml.etree.ElementTree as ET

    import pandas as pd

    from geo_stack.core.geo_utils import http_session

    url = f"{BRO_GLD_REST_BASE}/objects/{gld_id}"
    log.info("BRO GLD fetch: %s", url)

    session = http_session()
    try:
        resp = session.get(url, timeout=timeout_s)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise BROFetchError(f"BRO GLD fetch mislukt voor {gld_id}: {exc}") from exc

    # BRO GLD XML namespace varies per version; use local-name() pattern.
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise BROFetchError(f"GLD XML parse error voor {gld_id}: {exc}") from exc

    rows: list[tuple[datetime, float]] = []
    # Iter over MeasurementTVP elements regardless of namespace
    for tvp in root.iter():
        tag = tvp.tag.rsplit("}", 1)[-1]
        if tag != "MeasurementTVP":
            continue
        time_el = next((c for c in tvp if c.tag.endswith("time")), None)
        value_el = next((c for c in tvp if c.tag.endswith("value")), None)
        if time_el is None or value_el is None or value_el.text is None:
            continue
        try:
            t = pd.to_datetime(time_el.text, utc=True).tz_localize(None).normalize()
            v = float(value_el.text)
        except (ValueError, TypeError):
            continue
        rows.append((t, v))

    if not rows:
        log.warning("Geen meetwaarden gevonden in GLD %s", gld_id)
        return pd.Series(dtype="float64", name=gld_id)

    s = pd.Series(
        data=[v for _, v in rows],
        index=pd.DatetimeIndex([t for t, _ in rows], name="Datum"),
        name=gld_id,
    ).sort_index()

    if tmin is not None:
        s = s.loc[pd.to_datetime(tmin):]
    if tmax is not None:
        s = s.loc[:pd.to_datetime(tmax)]

    log.info("GLD %s: %d metingen, %s → %s", gld_id, len(s),
             s.index.min().date() if len(s) else "—",
             s.index.max().date() if len(s) else "—")
    return s


# ── CSV-parsers voor lokale bestanden ────────────────────────────────────────

def parse_dino_csv(path: Path | str) -> "pd.Series":
    """Parse een DINO Grondwaterstanden CSV-bestand.

    DINO-formaat:
    - Headers in regel 12 (skiprows=12)
    - NL datumformaat (DD-MM-YYYY)
    - Stand in cm t.o.v. NAP → geconverteerd naar m
    """
    import pandas as pd

    p = Path(path)
    df = pd.read_csv(p, skiprows=12, sep=",", quotechar='"', encoding="utf-8")
    df.columns = df.columns.str.strip().str.strip('"')

    if "Peildatum" not in df.columns or "Stand (cm t.o.v NAP)" not in df.columns:
        raise ValueError(
            f"DINO-bestand {p.name} mist verwachte kolommen 'Peildatum' / "
            f"'Stand (cm t.o.v NAP)'. Aanwezig: {list(df.columns)}"
        )

    df["Peildatum"] = pd.to_datetime(df["Peildatum"], format="%d-%m-%Y")
    s = (
        df.set_index("Peildatum")["Stand (cm t.o.v NAP)"]
        .dropna()
        .astype(float)
        / 100.0  # cm → m
    )
    s.index.name = "Datum"
    s.name = p.stem
    return s


def parse_bro_csv(path: Path | str) -> "pd.Series":
    """Parse een BRO grondwaterstand CSV-export.

    BRO-formaat heeft een variabele header-positie (afhankelijk van export);
    we detecteren de regel die ``"tijdstip meting"`` of ``"waterstand"`` bevat.
    Tijdzone-aware ISO-datums worden tz-stripped en op dag genormaliseerd.
    """
    import pandas as pd

    p = Path(path)
    with p.open(encoding="utf-8") as fh:
        regels = fh.readlines()

    header_idx: int | None = None
    for i, regel in enumerate(regels):
        if "tijdstip meting" in regel or "waterstand" in regel:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"BRO-bestand {p.name}: kon header niet detecteren "
            f"(zoekt 'tijdstip meting' of 'waterstand')"
        )

    df = pd.read_csv(p, skiprows=header_idx, sep=",", quotechar='"', encoding="utf-8")
    df.columns = df.columns.str.strip().str.strip('"')

    if "tijdstip meting" not in df.columns or "waterstand" not in df.columns:
        raise ValueError(
            f"BRO-bestand {p.name} mist 'tijdstip meting' of 'waterstand'. "
            f"Aanwezig: {list(df.columns)}"
        )

    df = df.dropna(subset=["waterstand"])
    df["tijdstip meting"] = (
        pd.to_datetime(df["tijdstip meting"], utc=True)
        .dt.tz_localize(None)
    )
    df = df.set_index("tijdstip meting")
    df.index = df.index.normalize()
    df.index.name = "Datum"

    s = pd.to_numeric(df["waterstand"], errors="coerce").dropna()
    s.name = p.stem
    return s
