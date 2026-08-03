# PastasDash

Grondwaterdashboard voor [PASTAS](https://pastas.dev): peilbuisreeksen bekijken,
tijdreeksmodellen fitten en GxG-statistiek aflezen — in de browser, zonder
programmeerkennis.

Bedoeld als opvolger van Menyanthes/Hydromonitor, en met dezelfde werkwijze:
je kiest links peilbuizen en die keuze blijft staan terwijl je naar reeksen,
modellen of statistiek kijkt.

## Installeren

Je hebt alleen [uv](https://docs.astral.sh/uv/) nodig; die regelt Python en
alle pakketten zelf.

```powershell
git clone https://github.com/FreeZo1223/pastasdash.git
cd pastasdash
uv run pastasdash-v2
```

Open daarna <http://127.0.0.1:8051>.

De eerste keer duurt even: uv haalt Python 3.12 en de pakketten op. Daarna
start het binnen enkele seconden. Er is **geen GitHub-account nodig** — alle
afhankelijkheden komen van PyPI.

Bijwerken naar een nieuwere versie:

```powershell
git pull
uv run pastasdash-v2
```

Handige opties: `--port 8052` (andere poort), `--reload` (herstart bij
codewijziging).

## Een dataset laden

Op de startpagina kun je drie dingen opgeven:

| Vorm | Wat het is |
|---|---|
| **PastaStore-map** | Map met een `.pastastore`-bestand plus `oseries/`, `stresses/`, `models/` — wat `pastastore` zelf wegschrijft. Geef de map òf het `.pastastore`-bestand op. |
| **PastaStore-ZIP** | Dezelfde store, ingepakt. |
| **BRO Loket-export** | Ruwe GMW-XML + GLD-CSV, als ZIP of uitgepakte map. Vereist `lesa_agent` (zie onder). |

De laatst gebruikte dataset wordt onthouden en bij de volgende start opnieuw
geladen.

### BRO Loket-exports

Rechtstreeks een BRO Loket-export inlezen vereist het pakket `lesa_agent`, dat
in een privérepo zit en dus niet automatisch meekomt. Zonder dat pakket werkt
het dashboard volledig; je laadt dan een PastaStore in plaats van een ruwe
export. Het dashboard vertelt het zelf wanneer je het nodig hebt.

## Weergaven

| Weergave | Waarvoor |
|---|---|
| **Reeksen** | Geselecteerde peilbuizen als tijdreeks, met de kaart erbij. |
| **Model** | Eén PASTAS-model bekijken of fitten (responsfunctie, ruismodel, periode). |
| **Vergelijken** | Meerdere gefitte modellen naast elkaar. |
| **Statistiek** | GxG, grondwatertrap, overschrijdingsduurlijn en regimecurve. |
| **Kaart** | Peilbuizen gekleurd op R², EVP of GxG. |
| **Droogte** | KNMI-neerslagtekort met percentielbanden; werkt los van de dataset. |

## GxG

GHG, GLG en GVG komen uit `pastas.stats` en worden niet zelf uitgerekend. Die
functies volgen de STIBOKA-conventie (14e/28e van de maand, hydrologisch jaar
april–maart) en laten jaren met te weinig metingen vallen.

Dat laatste is geen detail: zelf over álle jaren middelen geeft een te hoge GLG
zodra een reeks met een half winterjaar begint of eindigt — op een testreeks
scheelde dat 14 cm, genoeg om een grondwatertrap te verschuiven. Is een reeks te
kort voor een verantwoorde uitspraak, dan blijft het veld leeg in plaats van dat
er een onbetrouwbaar getal verschijnt.

Drempels staan in `pastasdash_v2/core/config.py` (`GXG_MIN_N_MEAS`,
`GXG_MIN_N_YEARS`).

De grondwatertrap heeft de maaiveldhoogte nodig. Ontbreekt die in de dataset,
dan toont de kolom `?` en zegt de pagina waarom.

## Opbouw

De code is gesplitst in een motor en een schil:

```
pastasdash_v2/
├── core/    motor — rekenwerk, opslag, caching. Geen UI.
│            Bruikbaar vanuit een notebook of script.
└── ui/      schil — NiceGUI: thema, vaste omlijsting, pagina's.
```

`core` mag niets uit `ui` importeren; `tests/test_architectuur.py` bewaakt dat.
Zo blijft het rekenwerk herbruikbaar en kan de interface later veranderen
zonder de berekeningen aan te raken.

Waar dingen bewaard worden:

| Doel | Pad |
|---|---|
| Instellingen en selecties | `~/.pastasdash_v2/state.db` |
| Berekende resultaten | `~/.pastasdash_v2/cache/` |
| KNMI-gegevens | `~/.pastasdash_v2/knmi_cache/` |

Opnieuw beginnen met een schone lei: verwijder de map `~/.pastasdash_v2`.

## Ontwikkelen

```powershell
uv run python -m pytest tests/ -q
uv run ruff check pastasdash_v2/
```

> Op sommige werkplekken blokkeert de virusscanner `uv run pytest`. Gebruik dan
> `uv run python -m pytest`, dat werkt wel.
