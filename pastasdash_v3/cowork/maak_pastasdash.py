"""
Zet PastasDash klaar voor een project: één HTML-bestand met de BRO-putnummers erin.

    python maak_pastasdash.py --out working/PastasDash_<project>.html \
        --titel "<projectnaam>" --putten GMW000000069526 GMW000000012345
    python maak_pastasdash.py --out ... --putten-bestand input/peilbuizen.csv
    python maak_pastasdash.py --out ... --grens input/projectgrens.gpkg [--laag naam] [--marge 250]

Met --grens zoekt het script de BRO-putten in het projectgebied (plus de marge
in meters). Lukt dat niet, omdat er hier geen internet is, dan gaat het gebied
mee in de pagina en zoekt de pagina de putten bij het openen.

Het script haalt verder niets op en rekent niets uit: de metingen haalt de
pagina uit de BRO zodra de collega hem opent. Drukt een samenvatting af als
JSON. Puur standaardbibliotheek.
"""

import argparse
import base64
import json
import os
import re
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo_io  # noqa: E402
import zoeken  # noqa: E402
from pastasdash_app import APP_ZB64, BRO_ZOEKEN, STAATBLOK, VERSIE  # noqa: E402

GMW = re.compile(r"GMW\d{12}")
MAX_PUTTEN = 60
# Ruim om Nederland heen; wat hierbuiten valt staat niet in RD New.
RD_BEREIK = (-10000, 280000, 300000, 640000)
# Meer knikpunten maakt de pagina zwaar zonder dat de zoekvraag beter wordt.
MAX_PUNTEN = 2000


def klaar(**velden) -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows schrijft anders in cp1252
    print(json.dumps(velden, ensure_ascii=False, indent=1))
    sys.exit(0 if velden.get("ok") else 1)


def lees_putten(woorden: list[str], bestand: str | None) -> tuple[list[str], list[str]]:
    """Putnummers uit de opdrachtregel en uit een bestand; plus wat niet herkend is."""
    tekst = " ".join(woorden).upper()
    if bestand:
        pad = Path(bestand)
        if not pad.exists():
            klaar(ok=False, melding=f"Het bestand met putnummers bestaat niet: {pad.name}")
        tekst += " " + pad.read_bytes().decode("utf-8", "replace").upper()
    putten = list(dict.fromkeys(GMW.findall(tekst)))
    onbekend = [w for w in " ".join(woorden).replace(",", " ").split() if not GMW.fullmatch(w.upper())]
    return putten, onbekend


def pak_uit(pad: Path, werkmap: Path) -> Path:
    """Een shapefile komt vaak als zip; pak hem uit en geef het geobestand terug."""
    doel = werkmap / ("_grens_" + pad.stem)
    doel.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pad) as z:
        for lid in z.infolist():
            naam = os.path.basename(lid.filename)
            if naam and not lid.is_dir():
                (doel / naam).write_bytes(z.read(lid))
    gevonden = sorted(f for f in doel.iterdir() if f.suffix.lower() in (".shp", ".gpkg", ".geojson"))
    if len(gevonden) != 1:
        klaar(ok=False, melding=f"In de zip zitten {len(gevonden)} geobestanden; lever er precies één aan.")
    return gevonden[0]


def lees_gebied(pad: Path, laag: str | None, werkmap: Path, waarschuwingen: list[str]) -> dict:
    """De projectgrens als GeoJSON-MultiPolygon in graden (lengte, breedte)."""
    if not pad.exists():
        klaar(ok=False, melding=f"Het bestand met de projectgrens bestaat niet: {pad.name}")
    if pad.suffix.lower() == ".zip":
        pad = pak_uit(pad, werkmap)
    if pad.suffix.lower() == ".gpkg" and laag is None:
        lagen = [n for n, _g, _s in geo_io.gpkg_layers(str(pad))]
        if len(lagen) > 1:
            klaar(ok=False, lagen=lagen,
                  melding="Het GeoPackage heeft meerdere lagen; geef met --laag aan welke de projectgrens is.")
    try:
        fc = geo_io.read_any(str(pad), laag)
    except ValueError as e:
        klaar(ok=False, melding=str(e))
    x0, y0, x1, y1 = geo_io.bounds(fc)
    if x0 < RD_BEREIK[0] or y0 < RD_BEREIK[1] or x1 > RD_BEREIK[2] or y1 > RD_BEREIK[3]:
        klaar(ok=False, melding="De coördinaten van de grens vallen buiten Nederland in RD New. Exporteer de "
                                "grens in QGIS naar RD New (EPSG:28992) of WGS84.")
    if sum(1 for _ in geo_io._iter_coords(fc)) > MAX_PUNTEN:
        geo_io.vereenvoudig(fc, 5.0)
        waarschuwingen.append("De grens is voor het zoeken vereenvoudigd (5 m); een put op de rand kan "
                              "er net in of net buiten vallen.")
    vlakken = []
    for ft in fc["features"]:
        g = ft["geometry"]
        vlakken += [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"] if g["type"] == "MultiPolygon" else []
    if not vlakken:
        klaar(ok=False, melding="De projectgrens bestaat uit lijnen of punten, niet uit vlakken; "
                                "daarin kan niet gezocht worden.")

    def graden(c):
        lat, lon = geo_io.rd_to_wgs84(c[0], c[1])
        return [round(lon, 6), round(lat, 6)]

    return {"type": "MultiPolygon", "coordinates": [[[graden(c) for c in r] for r in v] for v in vlakken]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="pad van het HTML-bestand dat gemaakt wordt")
    p.add_argument("--titel", default="", help="projectnaam; wordt de naam van het project in de pagina")
    p.add_argument("--putten", nargs="*", default=[], help="BRO-putnummers (GMW met twaalf cijfers)")
    p.add_argument("--putten-bestand", help="tekst- of csv-bestand waar de putnummers in staan")
    p.add_argument("--grens", help="projectgrens: .gpkg, .shp, .geojson of een .zip met een shapefile")
    p.add_argument("--laag", help="laag in het GeoPackage, als er meer dan één is")
    p.add_argument("--marge", type=float, default=0.0, help="ook putten tot zoveel meter buiten de grens")
    a = p.parse_args()

    uit = Path(a.out)
    uit.parent.mkdir(parents=True, exist_ok=True)
    putten, onbekend = lees_putten(a.putten, a.putten_bestand)
    waarschuwingen = []
    if onbekend:
        waarschuwingen.append(
            "Niet herkend als BRO-putnummer en daarom weggelaten: " + ", ".join(onbekend)
        )
    staat = {"titel": a.titel.strip(), "putten": []}

    gebied = None
    if a.grens:
        pad = Path(a.grens)
        gebied = {"bestand": pad.name, "marge_m": max(0.0, a.marge), "gezocht_door": None, "gevonden": None}
        vorm = lees_gebied(pad, a.laag, uit.parent, waarschuwingen)
        try:
            gevonden = zoeken.zoek_putten(BRO_ZOEKEN, vorm, gebied["marge_m"])
        except zoeken.TeGroot:
            klaar(ok=False, melding="In en rond dit gebied staan meer dan 2000 putten; de BRO levert ze dan "
                                    "niet. Kies een kleiner gebied of een kleinere marge.")
        except Exception as fout:  # noqa: BLE001 -- geen internet, een proxy, of een vreemd antwoord
            # Dan zoekt de pagina zelf; die heeft altijd internet nodig en dus ook hier.
            gebied["gezocht_door"] = "pagina"
            gebied["reden"] = type(fout).__name__
            staat["zoekgebied"] = {"naam": a.titel.strip() or pad.stem, "gebied": vorm, "marge_m": gebied["marge_m"]}
            staat["max_putten"] = MAX_PUTTEN
        else:
            gebied["gezocht_door"] = "cowork"
            gebied["gevonden"] = len(gevonden)
            gebied["verwijderd"] = sum(p["verwijderd"] for p in gevonden)
            gebied["buiten_grens"] = sum(p["afstand_m"] > 0 for p in gevonden)
            putten = list(dict.fromkeys(putten + [p["id"] for p in gevonden]))

    if len(putten) > MAX_PUTTEN:
        waarschuwingen.append(
            f"Er zijn {len(putten)} putnummers; de eerste {MAX_PUTTEN} zijn klaargezet. "
            "De rest kan de collega in de pagina zelf toevoegen."
        )
        putten = putten[:MAX_PUTTEN]
    staat["putten"] = putten

    html = zlib.decompress(base64.b64decode("".join(APP_ZB64))).decode("utf-8")
    if html.count(STAATBLOK) != 1:
        klaar(ok=False, melding="De ingebouwde pagina is beschadigd; de skill moet opnieuw gebouwd worden.")
    blok = STAATBLOK.replace("{}", json.dumps(staat, ensure_ascii=False).replace("<", "\\u003c"))
    uit.write_text(html.replace(STAATBLOK, blok), encoding="utf-8", newline="\n")

    klaar(
        ok=True,
        bestand=uit.name,
        versie=VERSIE,
        titel=staat["titel"],
        putten=putten,
        aantal_putten=len(putten),
        gebied=gebied,
        waarschuwingen=waarschuwingen,
        metingen_opgehaald=False,
        modellen_gemaakt=False,
    )


if __name__ == "__main__":
    main()
