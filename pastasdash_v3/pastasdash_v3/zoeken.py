"""Peilbuizen zoeken in een gebied, via de BRO.

Alleen standaardbibliotheek: dezelfde module draait in de pagina (werker) en
in de Cowork-skill (``scripts/zoeken.py``). Het gebied is GeoJSON in graden
(lengte, breedte), een Polygon, MultiPolygon of FeatureCollection daarvan.

De BRO zoekt alleen in een rechthoek en weigert meer dan 2000 putten. Wat in
de rechthoek valt, wordt hier op het gebied zelf gefilterd, eventueel met een
marge in meters erbuiten.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

# Meters per graad breedte; voor lengte maal cos(breedte). Op de schaal van een
# projectgebied scheelt dat hooguit een paar decimeter met RD.
_M_PER_GRAAD = 111_320.0


class TeGroot(Exception):
    """De BRO weigert: meer dan 2000 putten in de omsluitende rechthoek."""


def vlakken(geometrie: dict) -> list[list[list[list[float]]]]:
    """Alle polygonen uit een GeoJSON-object: [[buitenrand, gat, ...], ...]."""
    soort = geometrie.get("type")
    if soort == "FeatureCollection":
        return [v for f in geometrie.get("features", []) for v in vlakken(f)]
    if soort == "Feature":
        return vlakken(geometrie.get("geometry") or {})
    if soort == "Polygon":
        return [geometrie["coordinates"]]
    if soort == "MultiPolygon":
        return list(geometrie["coordinates"])
    return []


def omhullende(gebied: list, marge_m: float = 0.0) -> tuple[float, float, float, float]:
    """(zuid, west, noord, oost) in graden, ruim genoeg voor de marge."""
    lon = [c[0] for v in gebied for r in v for c in r]
    lat = [c[1] for v in gebied for r in v for c in r]
    if not lon:
        raise ValueError("Het gebied heeft geen vlakken.")
    dlat = marge_m / _M_PER_GRAAD
    dlon = marge_m / (_M_PER_GRAAD * math.cos(math.radians(max(abs(min(lat)), abs(max(lat))))))
    return min(lat) - dlat, min(lon) - dlon, max(lat) + dlat, max(lon) + dlon


def vraag(rechthoek: tuple[float, float, float, float]) -> dict:
    zuid, west, noord, oost = rechthoek
    return {"area": {"boundingBox": {"lowerCorner": {"lat": zuid, "lon": west},
                                     "upperCorner": {"lat": noord, "lon": oost}}}}


def _naam(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _tekst(el: ET.Element, naam: str) -> str:
    gevonden = next((e for e in el.iter() if _naam(e) == naam), None)
    return (gevonden.text or "").strip() if gevonden is not None else ""


def lees_antwoord(xml: str) -> list[dict]:
    """De putten uit een antwoord van de BRO: id, breedte, lengte, verwijderd."""
    wortel = ET.fromstring(xml)
    reden = _tekst(wortel, "rejectionReason")
    if reden:
        if "2000" in reden:
            raise TeGroot(reden)
        raise ValueError(f"De BRO weigert de zoekvraag: {reden}")
    putten = []
    for put in (e for e in wortel.iter() if _naam(e) == "GMW_C"):
        plek = next((e for e in put.iter() if _naam(e) == "standardizedLocation"), None)
        pos = _tekst(plek, "pos").split() if plek is not None else []
        if len(pos) != 2:
            continue
        putten.append({"id": _tekst(put, "broId"), "lat": float(pos[0]), "lon": float(pos[1]),
                       "verwijderd": _tekst(put, "removed") == "ja"})
    return putten


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return lon * _M_PER_GRAAD * math.cos(math.radians(lat0)), lat * _M_PER_GRAAD


def _in_ring(x: float, y: float, ring: list) -> bool:
    binnen = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            binnen = not binnen
        j = i
    return binnen


def _afstand_tot_ring(x: float, y: float, ring: list) -> float:
    beste = math.inf
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        dx, dy = bx - ax, by - ay
        lengte = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / lengte)) if lengte else 0.0
        beste = min(beste, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return beste


def afstand_tot_gebied(lat: float, lon: float, gebied: list) -> float:
    """0 binnen het gebied, anders de afstand in meters tot de dichtstbijzijnde rand."""
    x, y = _xy(lon, lat, lat)
    beste = math.inf
    for v in gebied:
        ringen = [[_xy(c[0], c[1], lat) for c in r] for r in v]
        if _in_ring(x, y, ringen[0]) and not any(_in_ring(x, y, g) for g in ringen[1:]):
            return 0.0
        beste = min(beste, *(_afstand_tot_ring(x, y, r) for r in ringen))
    return beste


def post(url: str, body: dict, timeout: float = 60) -> str:
    """POST met JSON; geeft de tekst terug, ook bij een weigering (HTTP 400)."""
    kop = {"Content-Type": "application/json", "Accept": "application/xml"}
    if sys.platform != "emscripten":
        # De BRO weigert aanroepen zonder herkenbare afzender (zie bro.py).
        kop["User-Agent"] = "Mozilla/5.0 (Eelerwoude PastasDash)"
    verzoek = urllib.request.Request(url, data=json.dumps(body).encode(), headers=kop, method="POST")
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as fout:
        tekst = fout.read().decode("utf-8", "replace")
        if "rejection" in tekst:
            return tekst
        raise


def zoek_putten(url: str, geometrie: dict, marge_m: float = 0.0, haal=post) -> list[dict]:
    """De BRO-putten in het gebied (plus marge), gesorteerd op putnummer.

    Elke put krijgt ``afstand_m``: 0 binnen het gebied, anders hoe ver erbuiten.
    """
    gebied = vlakken(geometrie)
    if not gebied:
        raise ValueError("Het gebied heeft geen vlakken; een lijn of punt is geen zoekgebied.")
    gevonden = lees_antwoord(haal(url, vraag(omhullende(gebied, marge_m))))
    uit = []
    for put in gevonden:
        afstand = afstand_tot_gebied(put["lat"], put["lon"], gebied)
        if afstand <= marge_m:
            uit.append({**put, "afstand_m": round(afstand)})
    return sorted(uit, key=lambda p: p["id"])
