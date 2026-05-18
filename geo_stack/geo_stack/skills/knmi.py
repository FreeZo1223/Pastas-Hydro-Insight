"""KNMI dagwaarden — neerslag (RD) en verdamping (EV24, Makkink).

API: https://daggegevens.knmi.nl/klimatologie/daggegevens

KNMI levert dagwaarden in 0.1 mm; deze skill converteert direct naar mm/dag
en zet ``-1`` (KNMI-flag voor 'ontbrekend') om naar ``NaN``. Voor PASTAS-
modellering hebben we beide reeksen nodig (``RechargeModel``).

Stations:
- Klimaatstations (~35 stuks) leveren neerslag + verdamping (RD + EV24).
- Neerslagstations (~325 stuks) leveren alleen RD.

Standaard-keuze voor LESA: het dichtstbijzijnde klimaatstation tot de AOI-
centroid. Helper :func:`nearest_climate_station` retourneert station-ID +
afstand op basis van een ingebakken station-tabel.
"""

from __future__ import annotations

import io
import logging
import math
import urllib.request
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)

KNMI_DAGGEGEVENS_URL = (
    "https://daggegevens.knmi.nl/klimatologie/daggegevens"
    "?stns={stn}&vars={var}&start={start}&end={end}"
)


# ── Klimaatstations (lat, lon, naam) ─────────────────────────────────────────
# Subset van actieve stations met EV24-rapportage. Coördinaten in WGS84.
# Bron: KNMI station-tabel (https://www.knmi.nl/nederland-nu/klimatologie/daggegevens).
_CLIMATE_STATIONS: dict[str, tuple[float, float, str]] = {
    "210": (52.171, 4.430, "Valkenburg"),
    "215": (52.141, 4.437, "Voorschoten"),
    "235": (52.928, 4.781, "De Kooy"),
    "240": (52.318, 4.790, "Schiphol"),
    "242": (53.241, 4.921, "Vlieland"),
    "248": (52.634, 5.176, "Wijdenes"),
    "249": (52.644, 4.979, "Berkhout"),
    "251": (53.392, 5.346, "Hoorn (Terschelling)"),
    "257": (52.506, 4.603, "Wijk aan Zee"),
    "260": (52.100, 5.180, "De Bilt"),
    "265": (52.130, 5.274, "Soesterberg"),
    "267": (52.898, 5.384, "Stavoren"),
    "269": (52.458, 5.520, "Lelystad"),
    "270": (53.224, 5.752, "Leeuwarden"),
    "273": (52.703, 5.888, "Marknesse"),
    "275": (52.056, 5.873, "Deelen"),
    "277": (53.413, 6.200, "Lauwersoog"),
    "278": (52.435, 6.259, "Heino"),
    "279": (52.750, 6.574, "Hoogeveen"),
    "280": (53.125, 6.585, "Eelde"),
    "283": (52.069, 6.657, "Hupsel"),
    "286": (53.196, 7.150, "Nieuw Beerta"),
    "290": (52.274, 6.891, "Twenthe"),
    "310": (51.442, 3.596, "Vlissingen"),
    "319": (51.226, 3.861, "Westdorpe"),
    "323": (51.527, 3.884, "Wilhelminadorp"),
    "330": (51.992, 4.122, "Hoek van Holland"),
    "344": (51.962, 4.447, "Rotterdam"),
    "348": (51.970, 4.926, "Cabauw"),
    "350": (51.566, 4.936, "Gilze-Rijen"),
    "356": (51.859, 5.146, "Herwijnen"),
    "370": (51.451, 5.377, "Eindhoven"),
    "375": (51.659, 5.707, "Volkel"),
    "377": (51.198, 5.763, "Ell"),
    "380": (50.906, 5.762, "Maastricht"),
    "391": (51.498, 6.197, "Arcen"),
    # Speciaal: 742 Terneuzen — afgesloten 2009 maar nog wel via daggegevens
    "742": (51.336, 3.829, "Terneuzen"),
}


def list_climate_stations() -> dict[str, tuple[float, float, str]]:
    """Geef alle bekende klimaatstations terug (id → (lat, lon, naam))."""
    return dict(_CLIMATE_STATIONS)


def nearest_climate_station(
    lat: float,
    lon: float,
    *,
    stations: dict[str, tuple[float, float, str]] | None = None,
) -> tuple[str, float, str]:
    """Vind het dichtstbijzijnde klimaatstation tot een WGS84-coordinaat.

    Returns
    -------
    (station_id, distance_km, name)
    """
    table = stations if stations is not None else _CLIMATE_STATIONS
    best: tuple[str, float, str] | None = None
    for stn, (slat, slon, name) in table.items():
        d_km = _haversine_km(lat, lon, slat, slon)
        if best is None or d_km < best[1]:
            best = (stn, d_km, name)
    if best is None:
        raise ValueError("Lege station-tabel")
    return best


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ── KNMI fetch + parse ───────────────────────────────────────────────────────

def _format_date(d: str | datetime) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    if "-" in d:
        return d.replace("-", "")
    return d


def fetch_knmi_dagwaarden(
    station: str,
    *,
    variables: str = "RD,EV24",
    start: str | datetime = "19900101",
    end: str | datetime | None = None,
    timeout_s: float = 30.0,
) -> "pd.DataFrame":
    """Fetch KNMI dagwaarden voor één station + variabelen.

    Parameters
    ----------
    station
        Station-ID (bijv. ``"260"`` voor De Bilt).
    variables
        Komma-gescheiden KNMI-variabelen (RD = neerslag in 0.1mm,
        EV24 = Makkink-verdamping in 0.1mm).
    start, end
        ``"YYYYMMDD"``, ``"YYYY-MM-DD"`` of ``datetime``. ``end=None`` =
        vandaag.

    Returns
    -------
    pd.DataFrame
        Index = ``DatetimeIndex`` per dag, kolommen per opgegeven variabele
        in originele KNMI-eenheid (0.1 mm). Gebruik :func:`to_neerslag_mm`
        en :func:`to_verdamping_mm` voor conversie naar mm/dag.
    """
    import pandas as pd

    end_d = end if end is not None else datetime.now()
    url = KNMI_DAGGEGEVENS_URL.format(
        stn=station,
        var=variables,
        start=_format_date(start),
        end=_format_date(end_d),
    )
    log.info("KNMI fetch: %s", url)

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310
            text = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise ConnectionError(f"KNMI fetch mislukt voor station {station}: {exc}") from exc

    # KNMI-CSV: commentaarregels beginnen met '#'. Header is de eerste niet-#-regel.
    lines = text.splitlines()
    data_start = 0
    for i, line in enumerate(lines):
        if not line.startswith("#") and line.strip():
            data_start = i
            break

    df = pd.read_csv(
        io.StringIO("\n".join(lines[data_start:])),
        skipinitialspace=True,
    )
    df.columns = df.columns.str.strip()
    if "YYYYMMDD" not in df.columns:
        raise ValueError(
            f"KNMI-respons mist 'YYYYMMDD'-kolom. Aanwezig: {list(df.columns)}"
        )
    df["YYYYMMDD"] = pd.to_datetime(df["YYYYMMDD"].astype(str), format="%Y%m%d")
    df = df.set_index("YYYYMMDD")
    df.index.name = "Datum"
    return df


def to_neerslag_mm(df: "pd.DataFrame") -> "pd.Series":
    """Extraheer neerslag (RD) als mm/dag-Series met NaN voor ontbrekend."""
    if "RD" not in df.columns:
        raise ValueError("KNMI-data mist 'RD'-kolom (neerslag).")
    s = df["RD"].copy().astype(float).replace(-1, float("nan")) / 10.0
    s.name = "Neerslag_mm"
    return s


def to_verdamping_mm(df: "pd.DataFrame") -> "pd.Series":
    """Extraheer Makkink-verdamping (EV24) als mm/dag-Series."""
    if "EV24" not in df.columns:
        raise ValueError(
            "KNMI-data mist 'EV24'-kolom (verdamping). Vraag het op via een "
            "klimaatstation, niet een neerslagstation."
        )
    s = df["EV24"].copy().astype(float).replace(-1, float("nan")) / 10.0
    s.name = "Verdamping_mm"
    return s


def fetch_recharge_inputs(
    station: str,
    *,
    start: str | datetime = "19900101",
    end: str | datetime | None = None,
    prefer: str = "hydropandas",
) -> tuple["pd.Series", "pd.Series"]:
    """Convenience: haal neerslag + verdamping op in één call.

    Probeert standaard eerst ``hydropandas`` (robuuster: retry-logica,
    Data Platform API als fallback bij endpoint-issues), valt terug op
    de directe urllib-route bij ImportError of falen.

    Parameters
    ----------
    station
        Station-ID (bijv. ``"260"``).
    start, end
        Begin/einddatum.
    prefer
        ``"hydropandas"`` (default) of ``"direct"`` om de directe API te
        forceren. De andere blijft altijd beschikbaar als fallback.

    Returns
    -------
    (neerslag_mm_per_dag, verdamping_mm_per_dag)
        Index = ``DatetimeIndex`` (datum, genormaliseerd op middernacht).
    """
    if prefer == "hydropandas":
        try:
            return _fetch_recharge_via_hpd(station, start=start, end=end)
        except (ImportError, ConnectionError) as exc:
            log.warning("hydropandas-fetch faalde, fallback naar directe API: %s", exc)
    df = fetch_knmi_dagwaarden(station, variables="RD,EV24", start=start, end=end)
    return to_neerslag_mm(df), to_verdamping_mm(df)


def _fetch_recharge_via_hpd(
    station: str,
    *,
    start: str | datetime,
    end: str | datetime | None,
) -> tuple["pd.Series", "pd.Series"]:
    """Haal neerslag + Makkink-verdamping op via hydropandas.

    Hydropandas wrapt de KNMI-endpoints en doet retry-logica en eenheids-
    conversie (waarden komen terug in meters; wij rekenen om naar mm/dag).
    Index wordt genormaliseerd naar dag-precisie zodat de reeks 1-op-1
    aansluit op de directe-API output.
    """
    import pandas as pd

    try:
        import hydropandas as hpd
    except ImportError as exc:
        raise ImportError(
            "hydropandas niet geïnstalleerd; gebruik prefer='direct' of "
            "installeer met 'uv add hydropandas'."
        ) from exc

    stn_int = int(station)
    end_eff = end if end is not None else datetime.now()
    try:
        prec_obs = hpd.PrecipitationObs.from_knmi(
            stn=stn_int, start=start, end=end_eff, meteo_var="RH",
        )
        evap_obs = hpd.EvaporationObs.from_knmi(
            stn=stn_int, start=start, end=end_eff, meteo_var="EV24",
        )
    except Exception as exc:  # noqa: BLE001 — wrap into ConnectionError voor consistent gedrag
        raise ConnectionError(f"hydropandas KNMI-fetch faalde voor station {station}: {exc}") from exc

    prec = _hpd_obs_to_mm_series(prec_obs, value_col="RH", name="Neerslag_mm")
    evap = _hpd_obs_to_mm_series(evap_obs, value_col="EV24", name="Verdamping_mm")
    return prec, evap


def _hpd_obs_to_mm_series(obs: Any, *, value_col: str, name: str) -> "pd.Series":  # noqa: ANN401
    """Normaliseer een hydropandas-Obs (DataFrame in meters) naar mm/dag-Series.

    Hydropandas levert waarden in meters terug met een DatetimeIndex op
    01:00:00 (KNMI-conventie: meting omstreeks 0900 UTC = volgende dag).
    We zetten om naar mm en normaliseren de index op middernacht.
    """
    import pandas as pd

    if value_col not in obs.columns:
        raise ValueError(f"Verwachtte kolom '{value_col}' in hydropandas-Obs, kreeg {list(obs.columns)}")
    s = obs[value_col].astype(float) * 1000.0  # m -> mm
    s.index = pd.to_datetime(s.index).normalize()
    s.index.name = "Datum"
    s.name = name
    return s


