"""Ophalen en cachen van KNMI dagelijkse klimaatdata voor het Droogte-tabblad.

Cachepad: ~/.pastasdash/droogte_cache/{station_code}_{start_year}.parquet

Kolommen in gecachede Parquet: datum (index), RH (mm/d), EV24 (mm/d).

Strategie:
1. Lees parquet-cache als die bestaat én vers genoeg is.
2. Anders: haal op via hydropandas (primair) of directe KNMI-URL (fallback).
3. Sla op in parquet-cache.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

_log = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".pastasdash" / "droogte_cache"
_CACHE_STALENESS_DAYS = 1  # herlaad als cache ouder is dan 1 dag


def _cache_path(station_code: int, start_year: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{station_code}_{start_year}.parquet"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = pd.Timestamp.now() - pd.Timestamp(path.stat().st_mtime, unit="s")
    return age.days < _CACHE_STALENESS_DAYS


def _fetch_via_hydropandas(station_code: int, start: str, end: str) -> pd.DataFrame:
    """Haal RH + EV24 op via hydropandas (beste succes-rate voor KNMI)."""
    import hydropandas as hpd

    stn = int(station_code)
    prec_obs = hpd.PrecipitationObs.from_knmi(
        stn=stn, start=start, end=end, meteo_var="RH"
    )
    evap_obs = hpd.EvaporationObs.from_knmi(
        stn=stn, start=start, end=end, meteo_var="EV24"
    )

    def _to_mm(obs, col: str) -> pd.Series:
        s = obs[col].astype(float) * 1000.0  # m -> mm
        s.index = pd.to_datetime(s.index).normalize()
        s.index.name = "datum"
        return s

    prec = _to_mm(prec_obs, "RH")
    evap = _to_mm(evap_obs, "EV24")
    df = pd.DataFrame({"RH": prec, "EV24": evap})
    df.index.name = "datum"
    return df.sort_index()


def _fetch_via_knmi_url(station_code: int, start: str, end: str) -> pd.DataFrame:
    """Fallback: KNMI daggegevens via open-data REST endpoint.

    Haalt uitsluitend RH en EV24 op.  Werkt zonder externe packages.
    """
    import io
    import urllib.request

    stn = str(station_code).zfill(3)
    url = (
        "https://www.daggegevens.knmi.nl/klimatologie/daggegevens?"
        f"stns={stn}&vars=RH:EV24&"
        f"start={start.replace('-', '')}&end={end.replace('-', '')}"
    )
    _log.debug("KNMI fallback URL: %s", url)
    with urllib.request.urlopen(url, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    lines = [l for l in raw.splitlines() if not l.startswith("#") and l.strip()]
    df = pd.read_csv(
        io.StringIO("\n".join(lines)),
        header=0,
        skipinitialspace=True,
    )
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"YYYYMMDD": "datum"})
    df["datum"] = pd.to_datetime(df["datum"].astype(str), format="%Y%m%d")
    df = df.set_index("datum").sort_index()

    for col in ("RH", "EV24"):
        df[col] = pd.to_numeric(df[col], errors="coerce") * 0.1  # 0.1 mm -> mm
        df[col] = df[col].clip(lower=0)

    return df[["RH", "EV24"]]


def fetch_knmi_daily(
    station_code: int,
    start_year: int = 1990,
    end_year: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Haal dagelijkse RH + EV24 op voor een KNMI-station.

    Parameters
    ----------
    station_code:
        KNMI-stationnummer (bijv. 260 voor De Bilt).
    start_year:
        Eerste jaar van de reeks (standaard 1990).
    end_year:
        Laatste jaar (standaard: huidig jaar).
    force_refresh:
        Negeer de cache en haal altijd vers op.

    Returns
    -------
    pd.DataFrame
        Kolommen ``RH`` en ``EV24`` (mm/d), DatetimeIndex ``datum``.
    """
    if end_year is None:
        end_year = pd.Timestamp.now().year

    cache_file = _cache_path(station_code, start_year)

    if not force_refresh and _is_fresh(cache_file):
        _log.info("Droogte-data uit cache: %s", cache_file)
        return pd.read_parquet(cache_file)

    start = f"{start_year}-01-01"
    end = f"{end_year}-12-31"

    df: pd.DataFrame | None = None
    try:
        _log.info("Ophalen KNMI %s via hydropandas (%s–%s)…", station_code, start_year, end_year)
        df = _fetch_via_hydropandas(station_code, start, end)
    except Exception as exc:
        _log.warning("hydropandas mislukt (%s); probeer directe URL…", exc)

    if df is None or df.empty:
        _log.info("Ophalen KNMI %s via daggegevens.knmi.nl…", station_code)
        df = _fetch_via_knmi_url(station_code, start, end)

    # Bewaar in cache
    try:
        df.to_parquet(cache_file)
        _log.info("Cache opgeslagen: %s", cache_file)
    except Exception as exc:
        _log.warning("Cache opslaan mislukt: %s", exc)

    return df
