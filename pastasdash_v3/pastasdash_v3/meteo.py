"""Neerslag en verdamping van het KNMI als verklarende reeksen bij een peilbuis.

PASTAS weigert reeksen met gaten. Ontbrekende dagen worden daarom aangevuld
met het dichtstbijzijnde station dat die dag wel heeft; hoeveel dagen dat
zijn, gaat als melding terug zodat de gebruiker het ziet.
"""

from __future__ import annotations

import math
from typing import Callable

import pandas as pd
import pyproj

from pastasdash_v2.core.config import CRS_RD, CRS_WGS84
from pastasdash_v2.core.knmi import fetch_knmi_daily
from pastasdash_v2.core.stations import DEFAULT_STATION_CODE, STATIONS, STATIONS_BY_CODE, KnmiStation
from pastasdash_v2.core.store import STORE
from pastasdash_v3.bronnen import BRONNEN

START_JAAR = 1960
MAX_BUREN = 3
# Langere gaten dan dit aantal dagen worden niet geïnterpoleerd.
MAX_INTERPOLEREN = 7
# Zoveel stations proberen we voor een put, dichtstbijzijnde eerst.
MAX_KANDIDATEN = 4

Ophaler = Callable[[int, int], pd.DataFrame]

# Stations die deze sessie geen bruikbare reeks bleken te hebben.
_ongeschikt: set[int] = set()


# Wat deze sessie al bij het KNMI is opgehaald. De kern bewaart het ook op
# schijf, maar dat lukt in de browser niet.
_opgehaald: dict[tuple[int, int], pd.DataFrame] = {}


def knmi_dag(station: int, start_jaar: int = START_JAAR) -> pd.DataFrame:
    """Neerslag (RH) en verdamping (EV24) in mm per dag; één keer per sessie opgehaald."""
    sleutel = (int(station), int(start_jaar))
    if sleutel not in _opgehaald:
        _opgehaald[sleutel] = fetch_knmi_daily(*sleutel)
    return _opgehaald[sleutel]


class GeenGegevens(ValueError):
    """Het station bestaat, maar heeft niet wat het model nodig heeft."""


def _afstand_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def stations_op_afstand(lat: float, lon: float) -> list[KnmiStation]:
    """Alle KNMI-stations, dichtstbijzijnde eerst."""
    return sorted(STATIONS, key=lambda s: _afstand_km(lat, lon, s.lat, s.lon))


def naam_stress(soort: str, code: int) -> str:
    return f"{'neerslag' if soort == 'prec' else 'verdamping'}_{code}"


def reeksen_voor(
    station: KnmiStation, haal: Ophaler = knmi_dag
) -> tuple[pd.Series, pd.Series, list[str]]:
    """Neerslag en verdamping in m/dag, zonder gaten, plus wat er is aangevuld."""
    df = haal(station.code, START_JAAR)[["RH", "EV24"]]
    compleet = df.dropna()
    if compleet.empty:
        raise GeenGegevens(f"station {station.name} meet niet zowel neerslag als verdamping")
    df = df.loc[compleet.index[0] : compleet.index[-1]].asfreq("D")

    meldingen: list[str] = []
    buren = [s for s in stations_op_afstand(station.lat, station.lon) if s.code != station.code]
    for buur in buren[:MAX_BUREN]:
        gaten = int(df.isna().any(axis=1).sum())
        if not gaten:
            break
        try:
            aanvulling = haal(buur.code, START_JAAR)[["RH", "EV24"]].reindex(df.index)
        except Exception as fout:  # noqa: BLE001 - een buur die niet antwoordt slaan we over
            meldingen.append(f"station {buur.name} niet bereikbaar: {fout}")
            continue
        df = df.fillna(aanvulling)
        gevuld = gaten - int(df.isna().any(axis=1).sum())
        if gevuld:
            meldingen.append(
                f"{gevuld} dagen zonder waarde bij {station.name} aangevuld met {buur.name}"
            )
    # Wat nu nog ontbreekt, heeft geen enkel station in de buurt. Een lang gat
    # vullen zou verzinnen zijn: de reeks begint dan na het laatste lange gat.
    leeg = df.isna().any(axis=1)
    if leeg.any():
        blok = (leeg != leeg.shift()).cumsum()[leeg]
        lang = [dagen for _, dagen in blok.groupby(blok) if len(dagen) > MAX_INTERPOLEREN]
        if lang:
            begin = lang[-1].index[-1] + pd.Timedelta(days=1)
            meldingen.append(
                f"de reeks van {station.name} begint op {begin.date().isoformat()}: daarvoor "
                f"ontbreken {sum(len(d) for d in lang)} dagen, ook bij omliggende stations"
            )
            df = df.loc[begin:]
        rest = int(df.isna().any(axis=1).sum())
        if rest:
            df = df.interpolate(limit_direction="both")
            meldingen.append(
                f"{rest} losse dagen zonder waarde bij {station.name} en omliggende stations: "
                "geïnterpoleerd"
            )

    prec = (df["RH"] / 1000.0).rename(naam_stress("prec", station.code))
    evap = (df["EV24"] / 1000.0).rename(naam_stress("evap", station.code))
    for s in (prec, evap):
        s.index.name = None
    return prec, evap, meldingen


def _bestaand_paar() -> tuple[str, str] | None:
    """Het ene neerslag-verdampingspaar dat al in het project zit, als dat er is."""
    df = STORE.pstore.stresses
    if df.empty or "kind" not in df.columns:
        return None
    prec = list(df.index[df["kind"] == "prec"])
    evap = list(df.index[df["kind"] == "evap"])
    return (prec[0], evap[0]) if len(prec) == 1 and len(evap) == 1 else None


def _voeg_toe(reeks: pd.Series, soort: str, station: KnmiStation) -> None:
    x, y = pyproj.Transformer.from_crs(CRS_WGS84, CRS_RD, always_xy=True).transform(
        station.lon, station.lat
    )
    STORE.pstore.add_stress(
        reeks,
        reeks.name,
        kind=soort,
        metadata={
            "x": round(x),
            "y": round(y),
            "station": station.code,
            "station_naam": station.name,
            "unit": "m/dag",
            "bron": BRONNEN["knmi"]["bron"],
        },
        overwrite=True,
    )


def _vers(put: str, prec_naam: str, evap_naam: str) -> bool:
    """Staan beide reeksen in het project en lopen ze tot de laatste meting?"""
    pstore = STORE.pstore
    if not {prec_naam, evap_naam} <= set(pstore.stresses_names):
        return False
    laatste_meting = pstore.get_oseries(put).dropna().index[-1]
    return pstore.get_stresses(prec_naam).dropna().index[-1] >= laatste_meting


def zorg_voor_stresses(
    put: str, haal: Ophaler = knmi_dag
) -> tuple[str, str, list[str]]:
    """Namen van de neerslag- en verdampingsreeks bij een put; haalt ze zo nodig op.

    Gaat de stations af van dichtbij naar ver, tot er een is dat zowel
    neerslag als verdamping meet.
    """
    rij = STORE.oseries().loc[put]
    meldingen: list[str] = []
    if pd.notna(rij.get("lat")) and pd.notna(rij.get("lon")):
        kandidaten = stations_op_afstand(float(rij["lat"]), float(rij["lon"]))[:MAX_KANDIDATEN]
    else:
        paar = _bestaand_paar()
        if paar:
            return (*paar, meldingen)
        kandidaten = [STATIONS_BY_CODE[DEFAULT_STATION_CODE]]
        meldingen.append(
            f"{put} heeft geen coördinaten; KNMI-station {kandidaten[0].name} gebruikt"
        )

    aanwezig = set(STORE.pstore.stresses_names)
    for station in kandidaten:
        if station.code in _ongeschikt:
            continue
        prec_naam, evap_naam = naam_stress("prec", station.code), naam_stress("evap", station.code)
        if _vers(put, prec_naam, evap_naam):
            return prec_naam, evap_naam, meldingen
        try:
            prec, evap, aangevuld = reeksen_voor(station, haal)
        except GeenGegevens as fout:
            _ongeschikt.add(station.code)
            meldingen.append(f"{fout}; volgende station geprobeerd")
            continue
        except Exception as fout:  # noqa: BLE001 - meestal: geen verbinding
            if {prec_naam, evap_naam} <= aanwezig:
                meldingen.append(
                    f"KNMI niet bereikbaar ({fout}); de eerder opgehaalde reeksen zijn gebruikt"
                )
                return prec_naam, evap_naam, meldingen
            paar = _bestaand_paar()
            if paar:
                meldingen.append(
                    f"KNMI niet bereikbaar ({fout}); de neerslag en verdamping uit het project "
                    "zijn gebruikt"
                )
                return (*paar, meldingen)
            raise RuntimeError(f"KNMI niet bereikbaar: {fout}") from fout
        _voeg_toe(prec, "prec", station)
        _voeg_toe(evap, "evap", station)
        meldingen.append(f"neerslag en verdamping van KNMI-station {station.name} opgehaald")
        return prec_naam, evap_naam, meldingen + aangevuld
    raise GeenGegevens(
        "geen KNMI-station in de buurt met neerslag en verdamping: " + "; ".join(meldingen)
    )
