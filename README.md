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

## Vereisten

- **Python 3.12** (3.13 mag ook)
- **uv** package-manager: <https://docs.astral.sh/uv/getting-started/installation/>
- Anthropic API-key voor de LESA-agent (zie `.env.example`)

## Installatie

```bash
git clone https://github.com/<jij>/GIS-projecten.git
cd GIS-projecten
uv sync                              # installeert álle workspace-packages
cp .env.example .env                 # vul ANTHROPIC_API_KEY in
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

## PASTAS-modellen inspecteren

Na een LESA-run met de grondwater-plugin staat er een PastaStore klaar onder:

```
sessions/<sessie-id>/data/grondwater_pastas/pastastore/lesa_<id>/
```

Open die in PastasDash:

```bash
uv run pastasdash
# Open http://127.0.0.1:8050 in de browser
# Klik "Load Pastastore" → navigeer naar het pad hierboven
```

Pastasdash toont:

- Kaart met peilbuislocaties
- Tijdreeksen per peilbuis (oseries)
- KNMI neerslag + verdamping (stresses)
- Gefitte PASTAS-modellen met diagnostiek

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
