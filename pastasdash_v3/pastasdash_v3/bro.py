"""Peilbuizen uit de BRO: putgegevens en stijghoogtereeksen.

Een put (GMW) heeft een of meer filters; elk filter heeft nul of meer
dossiers met metingen (GLD). Per filter komen alle dossiers samen in één
reeks van dagwaarden.
"""

from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import pandas as pd

from pastasdash_v3.bronnen import BRONNEN

_GMW = re.compile(r"^GMW\d{12}$")

# Volgorde waarin de waardekolommen van de BRO-reeks worden gebruikt: een
# beoordeelde meting gaat voor een voorlopige.
_KOLOMMEN = ("Beoordeelde Waarde", "Voorlopige Waarde", "Onbekend Waarde", "Controle Waarde")


def haal(url: str) -> str:
    """Haal een adres op als tekst."""
    kop = {}
    if sys.platform != "emscripten":
        # De BRO weigert aanroepen zonder herkenbare afzender; een browser
        # vult dit zelf in en staat niet toe dat een pagina het overschrijft.
        kop["User-Agent"] = "Mozilla/5.0 (Eelerwoude PastasDash)"
    with urllib.request.urlopen(urllib.request.Request(url, headers=kop), timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def is_putnummer(tekst: str) -> bool:
    return bool(_GMW.match(tekst))


def _naam(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _eerste(el: ET.Element | None, naam: str) -> ET.Element | None:
    if el is None:
        return None
    return next((e for e in el.iter() if _naam(e) == naam), None)


def _getal(el: ET.Element | None, naam: str) -> float | None:
    gevonden = _eerste(el, naam)
    try:
        return float(gevonden.text)
    except (AttributeError, TypeError, ValueError):
        return None


def _tekst(el: ET.Element | None, naam: str) -> str | None:
    gevonden = _eerste(el, naam)
    return gevonden.text.strip() if gevonden is not None and gevonden.text else None


def lees_put(xml: str) -> dict:
    """Ligging, maaiveld en filters uit het BRO-antwoord voor één put."""
    wortel = ET.fromstring(xml)
    put = _eerste(wortel, "GMW_PO")
    if put is None:
        put = _eerste(wortel, "GMW_PPO")
    if put is None:
        reden = _tekst(wortel, "rejectionReason") or "de BRO kent dit nummer niet"
        raise ValueError(reden)
    x = y = None
    pos = _tekst(_eerste(put, "deliveredLocation"), "pos")
    if pos:
        x, y = (float(v) for v in pos.split()[:2])
    filters = []
    for buis in (e for e in put.iter() if _naam(e) == "monitoringTube"):
        nummer = _tekst(buis, "tubeNumber")
        if nummer is None:
            continue
        filters.append(
            {
                "nummer": int(nummer),
                "bovenkant_buis": _getal(buis, "tubeTopPosition"),
                "filter_boven": _getal(buis, "screenTopPosition"),
                "filter_onder": _getal(buis, "screenBottomPosition"),
            }
        )
    return {
        "bro_id": _tekst(put, "broId"),
        "putcode": _tekst(put, "wellCode"),
        "nitg": _tekst(put, "nitgCode"),
        "x": x,
        "y": y,
        "maaiveld": _getal(_eerste(put, "deliveredVerticalPosition"), "groundLevelPosition"),
        "filters": sorted(filters, key=lambda f: f["nummer"]),
    }


def lees_relaties(tekst: str) -> dict[int, list[str]]:
    """Per filternummer de dossiers (GLD) met metingen."""
    uit: dict[int, list[str]] = {}
    for buis in json.loads(tekst).get("monitoringTubeReferences") or []:
        uit[int(buis["tubeNumber"])] = [g["broId"] for g in buis.get("gldReferences") or []]
    return uit


def lees_reeks(csv: str) -> pd.Series:
    """Metingen uit één dossier, in m NAP, op de klok van de BRO (UTC+1)."""
    d = pd.read_csv(io.StringIO(csv))
    if d.empty:
        return pd.Series(dtype=float)
    waarden = pd.concat(
        [
            pd.to_numeric(d[kolom], errors="coerce")
            for naam in _KOLOMMEN
            for kolom in d.columns
            if kolom.startswith(naam)
        ],
        axis=1,
    )
    s = waarden.bfill(axis=1).iloc[:, 0]
    # De BRO geeft milliseconden in UTC. Omgerekend naar wintertijd (UTC+1),
    # zodat een meting rond middernacht op de goede dag valt.
    s.index = pd.to_datetime(d.iloc[:, 0], unit="ms") + pd.Timedelta(hours=1)
    s = s.dropna().sort_index()
    return s[~s.index.duplicated(keep="last")]


def dagwaarden(reeksen: list[pd.Series]) -> pd.Series:
    """Voeg dossiers samen tot één reeks met het daggemiddelde."""
    gevuld = [s for s in reeksen if not s.empty]
    if not gevuld:
        return pd.Series(dtype=float)
    s = pd.concat(gevuld).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s = s.resample("D").mean().dropna()
    s.index.name = None
    return s


def haal_put(gmw: str) -> dict:
    """Putgegevens plus per filter een reeks dagwaarden.

    Geeft ``{"put": {...}, "filters": [{"naam", "reeks", "meta", "meldingen"}]}``.
    Een filter zonder metingen komt wel terug, met een lege reeks en de reden.
    """
    gmw = gmw.strip().upper()
    if not is_putnummer(gmw):
        raise ValueError(f"'{gmw}' is geen BRO-putnummer (GMW met twaalf cijfers)")
    adressen = BRONNEN["bro"]
    try:
        put = lees_put(haal(adressen["put"].format(gmw=gmw)))
        relaties = lees_relaties(haal(adressen["relaties"].format(gmw=gmw)))
    except urllib.error.HTTPError as fout:
        raise ValueError(f"de BRO geeft geen gegevens voor {gmw} (HTTP {fout.code})") from fout

    filters = []
    for f in put["filters"]:
        dossiers = relaties.get(f["nummer"], [])
        reeksen, meldingen = [], []
        if not dossiers:
            meldingen.append("geen metingen in de BRO")
        for gld in dossiers:
            try:
                reeksen.append(lees_reeks(haal(adressen["reeks"].format(gld=gld))))
            except Exception as fout:  # noqa: BLE001 - één kapot dossier mag de put niet tegenhouden
                meldingen.append(f"{gld} niet leesbaar: {fout}")
        reeks = dagwaarden(reeksen)
        if dossiers and reeks.empty:
            meldingen.append("de dossiers bevatten geen metingen")
        filters.append(
            {
                "naam": f"{gmw}_{f['nummer']}",
                "reeks": reeks,
                "meldingen": meldingen,
                "meta": {
                    "x": put["x"],
                    "y": put["y"],
                    "ground_level": put["maaiveld"],
                    "screen_top": f["filter_boven"],
                    "screen_bottom": f["filter_onder"],
                    "tube_top": f["bovenkant_buis"],
                    "tube_nr": f["nummer"],
                    "bro_id": gmw,
                    "putcode": put["putcode"],
                    "nitg": put["nitg"],
                    "gld": ", ".join(dossiers),
                    "unit": "m NAP",
                    "bron": BRONNEN["bro"]["bron"],
                    "bewerking": "daggemiddelde",
                },
            }
        )
    return {"put": put, "filters": filters}
