"""
Zet PastasDash klaar voor een project: één HTML-bestand met de BRO-putnummers erin.

    python maak_pastasdash.py --out working/PastasDash_<project>.html \
        --titel "<projectnaam>" --putten GMW000000069526 GMW000000012345
    python maak_pastasdash.py --out ... --putten-bestand input/peilbuizen.csv

Het script haalt zelf niets op en rekent niets uit. De pagina haalt de
metingen uit de BRO zodra de collega hem opent. Drukt een samenvatting af als
JSON. Puur standaardbibliotheek.
"""

import argparse
import base64
import json
import re
import sys
import zlib
from pathlib import Path

from pastasdash_app import APP_ZB64, STAATBLOK, VERSIE

GMW = re.compile(r"GMW\d{12}")
MAX_PUTTEN = 60


def klaar(**velden) -> None:
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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="pad van het HTML-bestand dat gemaakt wordt")
    p.add_argument("--titel", default="", help="projectnaam; wordt de naam van het project in de pagina")
    p.add_argument("--putten", nargs="*", default=[], help="BRO-putnummers (GMW met twaalf cijfers)")
    p.add_argument("--putten-bestand", help="tekst- of csv-bestand waar de putnummers in staan")
    a = p.parse_args()

    putten, onbekend = lees_putten(a.putten, a.putten_bestand)
    waarschuwingen = []
    if onbekend:
        waarschuwingen.append(
            "Niet herkend als BRO-putnummer en daarom weggelaten: " + ", ".join(onbekend)
        )
    if len(putten) > MAX_PUTTEN:
        waarschuwingen.append(
            f"Er zijn {len(putten)} putnummers gevonden; de eerste {MAX_PUTTEN} zijn klaargezet. "
            "De rest kan de collega in de pagina zelf toevoegen."
        )
        putten = putten[:MAX_PUTTEN]

    html = zlib.decompress(base64.b64decode("".join(APP_ZB64))).decode("utf-8")
    if html.count(STAATBLOK) != 1:
        klaar(ok=False, melding="De ingebouwde pagina is beschadigd; de skill moet opnieuw gebouwd worden.")
    staat = {"titel": a.titel.strip(), "putten": putten}
    blok = STAATBLOK.replace("{}", json.dumps(staat, ensure_ascii=False).replace("<", "\\u003c"))
    uit = Path(a.out)
    uit.parent.mkdir(parents=True, exist_ok=True)
    uit.write_text(html.replace(STAATBLOK, blok), encoding="utf-8", newline="\n")

    klaar(
        ok=True,
        bestand=uit.name,
        versie=VERSIE,
        titel=staat["titel"],
        putten=putten,
        aantal_putten=len(putten),
        waarschuwingen=waarschuwingen,
        metingen_opgehaald=False,
        modellen_gemaakt=False,
    )


if __name__ == "__main__":
    main()
