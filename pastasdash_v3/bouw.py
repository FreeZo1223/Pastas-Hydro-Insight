"""
Bouwt PastasDash v3 en de bijbehorende Cowork-skill.

    python bouw.py

Uitvoer in dist/:
  pastasdash.html                 de pagina: één bestand, rekenkern ingebouwd
  eelerwoude-pastasdash/          de skill-map voor M365 Copilot Cowork
  eelerwoude-pastasdash.zip       dezelfde map, klaar om te uploaden

Puur standaardbibliotheek. De rekenkern komt uit ../pastasdash_v2 (core en de
figuren) en uit pastasdash_v3/; die Python-bestanden gaan als tekst mee in de
pagina en draaien daar in de browser.
"""

import base64
import json
import re
import shutil
import zipfile
import zlib
from pathlib import Path

HIER = Path(__file__).resolve().parent
V2 = HIER.parent / "pastasdash_v2" / "pastasdash_v2"
DIST = HIER / "dist"
SKILL = "eelerwoude-pastasdash"
STAATBLOK = '<script id="pd-staat" type="application/json">{}</script>'

# Wat er van v2 mee moet: de hele motor, en van de schil alleen de figuren.
# De rest van de schil laadt NiceGUI en kan niet in de browser draaien.
V2_BESTANDEN = ["__init__.py", "ui/__init__.py", "ui/components/__init__.py", "ui/components/plots.py"]


def versie() -> str:
    tekst = (HIER / "pastasdash_v3" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', tekst).group(1)


def rekenkern() -> dict[str, str]:
    """Alle Python-bestanden die de werker nodig heeft, als pad -> tekst."""
    code = {}
    for pad in sorted((V2 / "core").glob("*.py")):
        code[f"pastasdash_v2/core/{pad.name}"] = pad.read_text(encoding="utf-8")
    for rel in V2_BESTANDEN:
        code[f"pastasdash_v2/{rel}"] = (V2 / rel).read_text(encoding="utf-8")
    for pad in sorted((HIER / "pastasdash_v3").glob("*.py")):
        code[f"pastasdash_v3/{pad.name}"] = pad.read_text(encoding="utf-8")
    code["pastasdash_v3/bronnen.json"] = (HIER / "bronnen.json").read_text(encoding="utf-8")
    verboden = [p for p, t in code.items() if re.search(r"^\s*(from|import) nicegui", t, re.M)]
    if verboden:
        raise SystemExit(f"Deze bestanden laden NiceGUI en kunnen niet mee: {verboden}")
    return code


def _json(waarde) -> str:
    # Binnen een <script>-blok mag de afsluiter niet letterlijk voorkomen.
    return json.dumps(waarde, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _js(pad: Path) -> str:
    tekst = pad.read_text(encoding="utf-8")
    return re.sub(r"</(script)", r"<\\/\1", tekst, flags=re.I).replace("<!--", "<\\!--")


def bouw_html() -> str:
    bronnen = json.loads((HIER / "bronnen.json").read_text(encoding="utf-8"))
    bronnen.pop("_toelichting", None)
    if not bronnen["plotly_js"]["versie"]:
        raise SystemExit("bronnen.json: plotly_js.versie is leeg.")
    html = (HIER / "src" / "app.html").read_text(encoding="utf-8")
    delen = {
        "/*CSS*/": (HIER / "src" / "app.css").read_text(encoding="utf-8"),
        "/*LEAFLET_CSS*/": (HIER / "vendor" / "leaflet.css").read_text(encoding="utf-8"),
        "/*LEAFLET_JS*/": _js(HIER / "vendor" / "leaflet.js"),
        "/*WERKER*/": _js(HIER / "src" / "werker.js"),
        "/*JS*/": _js(HIER / "src" / "app.js"),
        "__BRONNEN__": _json(bronnen),
        "__CODE__": _json(rekenkern()),
        "__STAAT__": "{}",
        "__VERSIE__": versie(),
    }
    for plek, inhoud in delen.items():
        if html.count(plek) != 1:
            raise SystemExit(f"Plaatshouder {plek} staat niet precies één keer in app.html.")
        html = html.replace(plek, inhoud)
    if STAATBLOK not in html:
        raise SystemExit("Het staat-blok ontbreekt in de gebouwde pagina.")
    return html


def bouw_skill(html: str) -> Path:
    doel = DIST / SKILL
    if doel.exists():
        shutil.rmtree(doel)
    (doel / "scripts").mkdir(parents=True)
    shutil.copy(HIER / "cowork" / "SKILL.md", doel / "SKILL.md")
    shutil.copy(HIER / "cowork" / "maak_pastasdash.py", doel / "scripts" / "maak_pastasdash.py")

    # Een skill-map mag geen .html/.js/.css bevatten; de pagina gaat daarom mee
    # als gecomprimeerde tekst in een Python-module.
    b64 = base64.b64encode(zlib.compress(html.encode("utf-8"), 9)).decode()
    regels = "\n".join(f'    "{b64[i:i + 100]}"' for i in range(0, len(b64), 100))
    (doel / "scripts" / "pastasdash_app.py").write_text(
        '"""PastasDash v3 (HTML), zlib-gecomprimeerd en base64-gecodeerd.\n\n'
        "Gegenereerd door bouw.py -- niet met de hand aanpassen.\n"
        '"""\n\n'
        f'VERSIE = "{versie()}"\n'
        f"STAATBLOK = {STAATBLOK!r}\n\n"
        f"APP_ZB64 = (\n{regels}\n)\n",
        encoding="utf-8",
        newline="\n",
    )
    zip_pad = DIST / f"{SKILL}.zip"
    with zipfile.ZipFile(zip_pad, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(doel.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f"{SKILL}/{f.relative_to(doel).as_posix()}")
    return zip_pad


def main() -> None:
    DIST.mkdir(exist_ok=True)
    html = bouw_html()
    pagina = DIST / "pastasdash.html"
    pagina.write_text(html, encoding="utf-8", newline="\n")
    zip_pad = bouw_skill(html)
    print(f"{pagina}  ({pagina.stat().st_size / 1024:.0f} kB)")
    print(f"{zip_pad}  ({zip_pad.stat().st_size / 1024:.0f} kB)")


if __name__ == "__main__":
    main()
