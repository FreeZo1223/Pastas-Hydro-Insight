"""KNMI daggegevens ophalen met parquet-cache.

Cache: ``~/.pastasdash_v2/knmi_cache/{station}_{start_year}.parquet``
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pastasdash_v2.config import KNMI_CACHE_DIR

log = logging.getLogger(__name__)

_STALENESS_DAYS = 1


def _cache_path(station: int, start_year: int) -> Path:
    return KNMI_CACHE_DIR / f"{station}_{start_year}.parquet"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = pd.Timestamp.now() - pd.Timestamp(path.stat().st_mtime, unit="s")
    return age.days < _STALENESS_DAYS


def _fetch_via_hydropandas(station: int, start: str, end: str) -> pd.DataFrame:
    import hydropandas as hpd

    prec_obs = hpd.PrecipitationObs.from_knmi(stn=int(station), start=start, end=end, meteo_var="RH")
    evap_obs = hpd.EvaporationObs.from_knmi(stn=int(station), start=start, end=end, meteo_var="EV24")

    def _mm(obs, col: str) -> pd.Series:
        s = obs[col].astype(float) * 1000.0
        s.index = pd.to_datetime(s.index).normalize()
        s.index.name = "datum"
        return s

    df = pd.DataFrame({"RH": _mm(prec_obs, "RH"), "EV24": _mm(evap_obs, "EV24")})
    df.index.name = "datum"
    return df.sort_index()


def _fetch_via_knmi_url(station: int, start: str, end: str) -> pd.DataFrame:
    import io
    import urllib.request

    stn = str(station).zfill(3)
    url = (
        "https://www.daggegevens.knmi.nl/klimatologie/daggegevens?"
        f"stns={stn}&vars=RH:EV24&start={start.replace('-', '')}&end={end.replace('-', '')}"
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    lines = [line for line in raw.splitlines() if not line.startswith("#") and line.strip()]
    df = pd.read_csv(io.StringIO("\n".join(lines)), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"YYYYMMDD": "datum"})
    df["datum"] = pd.to_datetime(df["datum"].astype(str), format="%Y%m%d")
    df = df.set_index("datum").sort_index()
    for col in ("RH", "EV24"):
        df[col] = pd.to_numeric(df[col], errors="coerce") * 0.1
        df[col] = df[col].clip(lower=0)
    return df[["RH", "EV24"]]


def fetch_knmi_daily(
    station: int, start_year: int = 1990, end_year: int | None = None, force_refresh: bool = False
) -> pd.DataFrame:
    """Dagelijkse RH + EV24 voor een KNMI-station met parquet-cache."""
    if end_year is None:
        end_year = pd.Timestamp.now().year
    cache_file = _cache_path(station, start_year)

    if not force_refresh and _is_fresh(cache_file):
        log.info("KNMI uit cache: %s", cache_file.name)
        return pd.read_parquet(cache_file)

    start, end = f"{start_year}-01-01", f"{end_year}-12-31"
    df: pd.DataFrame | None = None
    try:
        log.info("KNMI ophalen via hydropandas (%s, %s-%s)", station, start_year, end_year)
        df = _fetch_via_hydropandas(station, start, end)
    except Exception as exc:  # noqa: BLE001
        log.warning("hydropandas faalde (%s); val terug op directe URL", exc)

    if df is None or df.empty:
        df = _fetch_via_knmi_url(station, start, end)

    try:
        df.to_parquet(cache_file)
    except Exception as exc:  # noqa: BLE001
        log.warning("Parquet-cache opslaan faalde: %s", exc)
    return df
