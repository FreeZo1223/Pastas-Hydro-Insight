"""
Browsertest van de gebouwde pagina, tegen de echte BRO en het echte KNMI.

    C:\\GIS\\.venv\\Scripts\\python.exe tests\\browsertest.py

Heeft Playwright, Edge en internet nodig; duurt een paar minuten. Draait in
Edge, de browser van de collega's (een andere: PASTASDASH_BROWSER=chrome). De
kale testbrowser van Playwright crasht in stap 2 bij het herladen. Loopt na
wat een collega doet:

  1. het bestand lokaal openen, een put ophalen, een model fitten, alle
     weergaven langs, en het project als zip exporteren;
  2. een projectmap kiezen, daarin werken, de pagina herladen en dezelfde map
     weer openen;
  3. de zip en de projectmap openen met de rekenkern van de desktop (v2);
  4. een bestand openen dat Cowork zonder internet met een projectgrens
     maakte: de pagina zoekt dan zelf de putten in dat gebied.

De mappenkiezer van de browser vraagt een muisklik en is niet te bedienen
vanuit een test. Stap 2 vervangt hem door een map in de eigen opslag van de
browser: hetzelfde soort map-object, zonder het dialoogvenster. Die opslag
bestaat alleen op een webadres, dus stap 2 serveert de pagina op een
verzonnen adres.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HIER = Path(__file__).resolve().parent
PAGINA = HIER.parent / "dist" / "pastasdash.html"
V2 = HIER.parent.parent / "pastasdash_v2"
PUT = "GMW000000069526"
FILTER = PUT + "_2"
ADRES = "https://pastasdash.eelerwoude.test/"

NEPKIEZER = """
window.showDirectoryPicker = async () =>
  (await navigator.storage.getDirectory()).getDirectoryHandle('Proefproject', { create: true });
"""
LEES_MAP = """async () => {
  const uit = {};
  async function loop(map, voor) {
    for await (const [naam, h] of map.entries()) {
      if (h.kind === 'directory') await loop(h, voor + naam + '/');
      else {
        const b = new Uint8Array(await (await h.getFile()).arrayBuffer());
        let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
        uit[voor + naam] = btoa(s);
      }
    }
  }
  await loop(await (await navigator.storage.getDirectory()).getDirectoryHandle('Proefproject'), '');
  return uit;
}"""
DESKTOP = """
import json, os, sys, tempfile
os.environ["USERPROFILE"] = os.environ["HOME"] = tempfile.mkdtemp()
from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import model_summary
uit = {}
for pad in sys.argv[1:]:
    STORE.load_from_path(pad)
    naam = STORE.model_names()[0]
    uit[pad] = {"putten": STORE.oseries_names(), "modellen": STORE.model_names(),
                "rsq": model_summary.__wrapped__(STORE.store_key, naam)["rsq"]}
print("UITKOMST" + json.dumps(uit))
"""

fouten: list[str] = []


def toets(naam: str, goed: bool, detail: str = "") -> None:
    print(f"{time.strftime('%H:%M:%S')} {'ok  ' if goed else 'FOUT'}  {naam}{'  -- ' + detail if detail and not goed else ''}", flush=True)
    if not goed:
        fouten.append(naam)


def rustig(pg: Page, seconden: int = 180) -> None:
    """Wacht tot de rekenkern niets meer te doen heeft."""
    pg.wait_for_function("document.getElementById('bezig').hidden", timeout=seconden * 1000)
    pg.wait_for_timeout(700)


def start(pg: Page, adres: str) -> None:
    pg.goto(adres)
    pg.wait_for_function("document.body.dataset.klaar === 'ja'", timeout=300_000)


def roep(pg: Page, naam: str, args: dict | None = None):
    return pg.evaluate("([n, a]) => PD.roep(n, a)", [naam, args or {}])


def tab(pg: Page, naam: str) -> None:
    pg.click(f"[data-tab={naam}]")
    rustig(pg)
    pg.wait_for_timeout(1200)


def luister(pg: Page, bak: list[str]) -> None:
    pg.on("pageerror", lambda e: bak.append(str(e)))
    pg.on("console", lambda m: bak.append(m.text) if m.type == "error" else None)


def stap_lokaal_bestand(browser, uit: Path) -> float:
    print("\n1. Lokaal bestand", flush=True)
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    pg.set_default_timeout(120_000)
    schermfouten: list[str] = []
    luister(pg, schermfouten)
    start(pg, PAGINA.as_uri())
    versies = pg.evaluate("PD.S.versies")
    toets("rekenkern start vanaf een lokaal bestand", versies["pastas"].startswith("2."), str(versies))
    bronnen = json.loads((HIER.parent / "bronnen.json").read_text(encoding="utf-8"))
    toets("Plotly in de pagina past bij Plotly in Python", versies["plotly_js"] == bronnen["plotly_js"]["versie"], str(versies))

    tab(pg, "droogte")
    pg.click("#knop-droogte")
    rustig(pg)
    toets("neerslagtekort zonder project", pg.locator("#vlak .js-plotly-plot").count() == 1)

    tab(pg, "project")
    pg.click("#knop-leeg")
    rustig(pg)
    pg.fill("#bro-invoer", f"{PUT} GMW000000000000")
    pg.click("#knop-bro")
    rustig(pg)
    verslag = pg.inner_text("#bro-verslag")
    toets("put uit de BRO geeft twee filters", f"{PUT}_1" in verslag and FILTER in verslag, verslag)
    toets("onbekende put geeft een melding, geen crash", "GMW000000000000: " in verslag, verslag)
    toets("werk zonder map staat als niet opgeslagen in de kop", "Niet opgeslagen" in pg.inner_text("#opslag"))

    tab(pg, "reeksen")
    toets("reeksen: grafiek", pg.locator("#vlak .js-plotly-plot").count() == 1)
    toets("reeksen: beide filters op de kaart", pg.locator("#vlak .leaflet-interactive").count() == 2)

    pg.evaluate(f"PD.zetSelectie(['{FILTER}'])")
    tab(pg, "model")
    toets("model: nog geen model", "Nog geen model" in pg.inner_text("#model-uitkomst"))
    pg.click("#knop-fit")
    rustig(pg, 300)
    pg.wait_for_timeout(1500)
    fitverslag = pg.inner_text("#fit-verslag")
    toets("fit meldt welk KNMI-station is gebruikt", "KNMI-station" in fitverslag, fitverslag)
    rsq = roep(pg, "model", {"naam": FILTER})["samenvatting"]["rsq"]
    toets("fit geeft een R²", isinstance(rsq, float) and 0.2 < rsq < 1, str(rsq))
    toets("model: resultaten en diagnostiek getekend", pg.locator("#model-uitkomst .js-plotly-plot").count() == 2)

    tab(pg, "vergelijk")
    toets("vergelijken: tabel met het model", FILTER in pg.inner_text("#tabel-vergelijk"))
    pg.evaluate(f"PD.zetSelectie(['{PUT}_1', '{FILTER}'])")
    tab(pg, "statistiek")
    tabel = pg.inner_text("#tabel-statistiek")
    toets("statistiek: GxG-tabel met grondwatertrap", "VIII" in tabel and "null" not in pg.inner_text("#vlak"), tabel)
    toets("statistiek: drie grafieken", pg.locator("#vlak .js-plotly-plot").count() == 3)
    tab(pg, "kaart")
    toets("kaart: putten met legenda", pg.locator("#vlak .leaflet-interactive").count() == 2 and pg.locator(".kaart-balk").count() == 1)

    tab(pg, "project")
    with pg.expect_download() as wacht:
        pg.click("#knop-zip")
    wacht.value.save_as(uit / "export.zip")
    toets("zip geëxporteerd", (uit / "export.zip").stat().st_size > 10_000)
    toets("geen fouten in de pagina", not schermfouten, "; ".join(schermfouten)[:400])
    pg.close()
    return rsq


def stap_projectmap(browser, uit: Path) -> float:
    print("\n2. Projectmap", flush=True)
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    ctx.route(ADRES + "**", lambda r: r.fulfill(body=PAGINA.read_text(encoding="utf-8"), content_type="text/html"))
    ctx.add_init_script(NEPKIEZER)
    pg = ctx.new_page()
    pg.set_default_timeout(120_000)
    schermfouten: list[str] = []
    luister(pg, schermfouten)
    start(pg, ADRES)
    pg.click("#knop-map")
    rustig(pg)
    toets("lege map wordt een nieuw project", pg.evaluate("PD.S.toestand.naam") == "Proefproject")
    pg.fill("#bro-invoer", PUT)
    pg.click("#knop-bro")
    rustig(pg)
    pg.evaluate(f"PD.zetSelectie(['{FILTER}'])")
    tab(pg, "model")
    pg.click("#knop-fit")
    rustig(pg, 300)
    rsq = roep(pg, "model", {"naam": FILTER})["samenvatting"]["rsq"]
    toets("kop meldt dat het in de map staat", "Opgeslagen in map Proefproject" in pg.inner_text("#opslag"), pg.inner_text("#opslag"))
    bestanden = pg.evaluate(LEES_MAP)
    verwacht = {"Proefproject.pastastore", f"oseries/{FILTER}.pas", f"models/{FILTER}.pas"}
    toets("reeksen en model staan als bestanden in de map", verwacht <= set(bestanden), str(sorted(bestanden)))
    toets("ook de KNMI-reeksen staan in de map", sum(n.startswith("stresses/") and not n.endswith("_meta.pas") for n in bestanden) == 2)

    pg.reload()
    pg.wait_for_function("document.body.dataset.klaar === 'ja'", timeout=300_000)
    toets("na herladen biedt de pagina de vorige map aan", pg.locator("#knop-heropen").count() == 1)
    pg.click("#knop-map")
    rustig(pg)
    toestand = pg.evaluate("PD.S.toestand")
    toets("na herladen staat het model er nog", toestand["modellen"] == [FILTER], str(toestand["modellen"]))
    rsq_terug = roep(pg, "model", {"naam": FILTER})["samenvatting"]["rsq"]
    toets("teruggelezen model geeft dezelfde R²", abs(rsq_terug - rsq) < 1e-9, f"{rsq} tegen {rsq_terug}")
    roep(pg, "verwijder_put", {"naam": f"{PUT}_1"})
    rustig(pg)
    toets("verwijderde put verdwijnt ook uit de map", f"oseries/{PUT}_1.pas" not in pg.evaluate(LEES_MAP))

    for pad, inhoud in pg.evaluate(LEES_MAP).items():
        doel = uit / "Proefproject" / pad
        doel.parent.mkdir(parents=True, exist_ok=True)
        doel.write_bytes(base64.b64decode(inhoud))
    toets("geen fouten in de pagina", not schermfouten, "; ".join(schermfouten)[:400])
    ctx.close()
    return rsq


def stap_desktop(uit: Path, rsq_zip: float, rsq_map: float) -> None:
    print("\n3. Openen met de rekenkern van de desktop (v2)", flush=True)
    python = V2 / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        toets("omgeving van v2 gevonden", False, f"{python} bestaat niet; draai 'uv sync' in pastasdash_v2")
        return
    paden = [str(uit / "export.zip"), str(uit / "Proefproject")]
    r = subprocess.run([str(python), "-c", DESKTOP, *paden], capture_output=True, text=True, cwd=V2)
    regel = next((x for x in r.stdout.splitlines() if x.startswith("UITKOMST")), None)
    if regel is None:
        toets("desktop opent de zip en de map", False, r.stderr[-600:])
        return
    gelezen = json.loads(regel[len("UITKOMST"):])
    toets("desktop opent de zip", gelezen[paden[0]]["modellen"] == [FILTER], str(gelezen[paden[0]]))
    toets("desktop rekent dezelfde R² uit de zip", abs(gelezen[paden[0]]["rsq"] - rsq_zip) < 1e-6, f"{gelezen[paden[0]]['rsq']} tegen {rsq_zip}")
    toets("desktop opent de projectmap", gelezen[paden[1]]["putten"] == [FILTER], str(gelezen[paden[1]]))
    toets("desktop rekent dezelfde R² uit de map", abs(gelezen[paden[1]]["rsq"] - rsq_map) < 1e-6, f"{gelezen[paden[1]]['rsq']} tegen {rsq_map}")


def stap_zoekgebied(browser, uit: Path) -> None:
    print("\n4. Projectgrens, putten zoekt de pagina", flush=True)
    sys.path.insert(0, str(HIER.parent))
    from pastasdash_v3 import zoeken
    from pastasdash_v3.bronnen import BRONNEN

    # Een vierkant van ruim 600 m rond de proefput bij Axel.
    vierkant = [[3.531, 51.575], [3.541, 51.575], [3.541, 51.581], [3.531, 51.581], [3.531, 51.575]]
    grens = uit / "grens.geojson"
    grens.write_text(json.dumps({"type": "Polygon", "coordinates": [vierkant]}), encoding="utf-8")
    verwacht = [q["id"] for q in zoeken.zoek_putten(BRONNEN["bro"]["zoeken"], {"type": "Polygon", "coordinates": [vierkant]})]
    script = HIER.parent / "dist" / "eelerwoude-pastasdash" / "scripts" / "maak_pastasdash.py"
    omgeving = dict(os.environ, HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")
    r = subprocess.run([sys.executable, str(script), "--out", str(uit / "zoek.html"), "--titel", "Axel", "--grens", str(grens)],
                       capture_output=True, text=True, encoding="utf-8", env=omgeving)
    samen = json.loads(r.stdout)
    toets("Cowork zonder internet laat het zoeken aan de pagina", samen["gebied"]["gezocht_door"] == "pagina", r.stdout[-300:])

    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    schermfouten: list[str] = []
    luister(pg, schermfouten)
    start(pg, (uit / "zoek.html").as_uri())
    rustig(pg, 300)
    verslag = pg.evaluate("PD.S.broVerslag.map(r => r.tekst).join(' | ')")
    toets("de pagina vindt evenveel putten als Cowork zou vinden", f"{len(verwacht)} BRO-putten in Axel" in verslag,
          f"verwacht {len(verwacht)}: {verslag[:300]}")
    namen = pg.evaluate("PD.S.toestand.putten.map(p => p.naam)")
    toets("en haalt hun reeksen op", bool(namen) and all(n.rsplit("_", 1)[0] in verwacht for n in namen), str(namen))
    toets("geen schermfouten bij zoeken", not schermfouten, "; ".join(schermfouten[:3]))
    pg.screenshot(path=str(uit / "zoekgebied.png"))
    pg.close()


def main() -> int:
    if not PAGINA.exists():
        print(f"{PAGINA} bestaat niet; draai eerst bouw.py")
        return 1
    uit = Path(tempfile.mkdtemp(prefix="pastasdash_v3_browsertest_"))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("PASTASDASH_BROWSER", "msedge"))
        rsq_zip = stap_lokaal_bestand(browser, uit)
        rsq_map = stap_projectmap(browser, uit)
        stap_zoekgebied(browser, uit)
        browser.close()
    stap_desktop(uit, rsq_zip, rsq_map)
    print(f"\n{'ALLES IN ORDE' if not fouten else str(len(fouten)) + ' FOUT: ' + '; '.join(fouten)}")
    print(f"Uitvoer van de test: {uit}")
    return 1 if fouten else 0


if __name__ == "__main__":
    sys.exit(main())
