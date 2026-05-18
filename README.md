# GIS-projecten — werkplek voor ecohydrologen

Een verzameling Python-tools voor landschapsecologisch onderzoek met focus op
hydrologie en grondwater. Centraal staat een **LESA-agent** (Landschaps­
Ecologisch Systeem­Analyse) die data uit publieke bronnen (PDOK, BRO, KNMI)
combineert met een **PastaStore + PastasDash**-dashboard voor het bouwen en
inspecteren van PASTAS-tijdreeksmodellen — vergelijkbaar met hoe je vroeger
met Menyanthes en Hydromonitor werkte.

## Werkstroom in vier stappen

```
1. lesa-agent  →  haalt peilbuizen + KNMI op
                  fit PASTAS RechargeModels
                  schrijft alles in een PastaStore
2. pastasdash  →  browsergebaseerde GUI om peilbuizen
                  en modellen te bekijken / bij te stellen
3. (handwerk) →   modelinterpretatie, hypotheses noteren
4. QGIS       →   ruimtelijke verbeelding van resultaten
```

## Eenmalige machine-setup

Twee dingen heb je op je werkmachine nodig — daarna doet `uv sync` de rest.

### 1. Python 3.12 (of 3.13)

Controleer eerst of je Python al hebt:

```powershell
python --version
```

Krijg je `Python 3.12.x` of `3.13.x` terug → klaar. Anders installeren:

- **Windows:** `winget install -e --id Python.Python.3.12` (of download van
  <https://www.python.org/downloads/>)
- **macOS:** `brew install python@3.12`
- **Linux:** via je package-manager of `pyenv`

### 2. uv package-manager

`uv` regelt de venv, installeert alle dependencies en draait commando's.
Installatie:

- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  of `winget install astral-sh.uv`
- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

Controleer:

```bash
uv --version
```

### 3. (Optioneel) Anthropic API-key

Alleen nodig als je de **LESA-agent** wilt draaien (niet voor pastasdash).
Verkrijg via <https://console.anthropic.com/>; zet in je `.env`.

## Project installeren

```bash
git clone https://github.com/<jij>/GIS-projecten.git
cd GIS-projecten
uv sync                              # installeert álle workspace-packages
cp .env.example .env                 # vul ANTHROPIC_API_KEY in (optioneel)
```

Eén `uv sync` installeert alles wat je nodig hebt: `geo_stack`, `BeSI`,
`lesa`, `lesa_agent`, `pastas_adapter` en `pastasdash`. Plus alle externe
afhankelijkheden zoals `pastas`, `pastastore`, `hydropandas`, `geopandas`,
`rasterio`.

KNMI- en BRO-data worden bij voorkeur opgehaald via **hydropandas**
(robuuste retry + KNMI Data Platform fallback). De directe REST-route blijft
beschikbaar als reserve. Grondwaterstand-ID's mogen zowel `GLD…` als `GMW…`
zijn — hydropandas dispatchet automatisch.

## LESA-sessie starten

```bash
uv run lesa-agent \
  --aoi pad/naar/aoi.geojson \
  --project "Naam onderzoeksgebied" \
  --scale 2 \
  --landscape duinen
```

De agent stelt vragen en draait plugins (geomorfologie, bodem, grondwater)
om een gebiedsbeschrijving op te bouwen. Sessies komen onder `sessions/`.

Tip: typ `quit` om te eindigen, alle tussenresultaten blijven bewaard.

## PastasDash — peilbuizen analyseren

Twee paden, beide met hetzelfde eindresultaat in de browser op
<http://127.0.0.1:8050/>:

### A. Direct uit BRO-uitgifteloket (snelst voor losse analyse)

```bash
uv run pastasdash       # start de browser-GUI op localhost:8050
```

In de dashboard: klik **Load Pastastore** → selecteer de ZIP die je
download van <https://www.broloket.nl/> (sleep een gebied, vraag aan,
ontvang `…@…_<datum>.zip`). PastasDash herkent het BRO-Loket-format
automatisch, parsed XML's + GLD-CSV's, vraagt KNMI op voor het
dichtstbijzijnde klimaatstation en bouwt in-memory een PastaStore.

> Eerste keer duurt ~10 seconden door de KNMI-fetch. Resultaat is niet
> bewaard — herstarten = opnieuw bouwen. Voor herbruikbare stores: zie B.

### B. Via LESA-agent of CLI-converter (resultaat bewaard)

Voor een herbruikbaar `.zip` met PASTAS-modellen al meegerekend:

```bash
uv run lesa-bro-to-pastastore <bro-loket.zip> --fit-models
# -> schrijft <bro-loket>_pastastore.zip naast de input
uv run pastasdash
# upload _pastastore.zip in de dashboard
```

Of via de LESA-agent (zie hierboven): na een agent-sessie staat er
automatisch een PastaStore-ZIP onder
`sessions/<sessie-id>/data/grondwater_pastas/pastastore/...`.

### Wat je in het dashboard ziet

| Tab | Inhoud |
|---|---|
| **Overview** | Tabel met alle peilbuizen + KNMI-stresses, hun metadata |
| **Maps** | Kaart met peilbuislocaties (RD-coords uit GMW-XML's) |
| **Model** | Per peilbuis: PASTAS-fit, simulatie vs metingen, parameters, R² |
| **Compare** | Meerdere modellen naast elkaar |

## Workspace-structuur

| Map | Inhoud |
|---|---|
| `geo_stack/` | Canonieke data-acquisitielaag (PDOK, BRO, KNMI, STAC) |
| `BeSI/` | Habitatgeschiktheid op basis van soortenkansenkaarten |
| `lesa-agent-v2/packages/lesa/` | LESA-kern: domein, plugins, sessie-store |
| `lesa-agent-v2/packages/lesa_agent/` | LLM-harness: Anthropic + MCP-server |
| `PASTAS/pastas_adapter/` | Boundary-laag tussen LESA en PASTAS |
| `PASTAS/pastasdash/` | Dash-app voor PASTAS-modelinspectie |
| `Archief/` | Oude code en gekloonde libraries (niet gepushed) |

## Hulp / documentatie

- `CLAUDE.md` — werkinstructies voor AI-assistenten + datawegwijzer
- `geo_stack/README.md` — endpoints en cache-strategie voor data-fetches
- `PASTAS/README.md` — historische werkstroom en notebooks
- `lesa-agent-v2/README.md` — agent-architectuur en plugin-API

## Bijdragen

Plugins voor nieuwe rangorde-niveaus zijn welkom. Zie
`lesa-agent-v2/scripts/new_plugin.py` voor een sjabloon.
