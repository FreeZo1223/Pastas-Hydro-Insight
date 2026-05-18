# LESA Agent v2 — Claude Code projectinstructies

Dit document is voor jou (Claude Code) tijdens werk in deze repo.
Lees `docs/ARCHITECTURE.md` voor de inhoudelijke architectuur en
`README.md` voor gebruikers-getting-started. Deze CLAUDE.md beschrijft
**werkwijze, conventies, en harde regels** voor jouw eigen werk.

---

## 1. Wat dit project is

Een agentic LESA-pipeline (LandschapsEcologische Systeem Analyse, NL).
Bouwt op de v1-leerschool (`C:\GIS_Projecten\lesa-agent\OVERZICHT_LESA_AGENT.md`)
en op `geo_stack` (`C:\GIS_Projecten\geo_stack\`) als data-laag. Doel:
**bureauondersteuner + hypothesegenerator + veldwerk-voorbereider**, niet
een rapport-generator. De hydroloog/ecoloog/bodemkundige is en blijft
eindverantwoordelijk.

Methodologische bron: LESA.INFO, OBN, Handboek Ecohydrologische
Systeemanalyse Beekdallandschappen, Rangordemodel Bakker (1979). Zie
`C:\GIS_Projecten\lesa-agent\LESA_systeemanalyse.md`.

---

## 2. Repo-structuur (high level)

```
C:\GIS_Projecten\
├── geo_stack/           # CANONIEKE data-laag (los project, path-dep)
│   └── geo_stack/{core,skills}/
│       └── skills/{ahn,bgt,bro/,knmi,kadaster,gee,ndvi_stac,cloud_native}
├── pastas_adapter/      # PASTAS-API wrapper (los project, path-dep)
│   └── pastas_adapter/{fit,store,diagnostics}
└── lesa-agent-v2/
    ├── docs/            # ARCHITECTURE.md, METHODOLOGY.md, ADR's
    ├── packages/
    │   └── lesa/        # LESA-specifieke logica (plugins, agent, session, mcp)
    ├── examples/
    │   └── burgh_haamstede/  # canonieke testcase (Provincie Zeeland)
    └── scripts/
```

`geo_stack` en `pastas_adapter` zijn **niet langer** workspace-members;
ze zijn externe path-dependencies (`pyproject.toml`:
`geo-stack-nl = { path = "../geo_stack" }`,
`pastas-adapter = { path = "../pastas_adapter" }`).
Wijzigingen zijn direct zichtbaar via editable install. Andere projecten
(BeSI, Connectiviteit, PASTAS-dashboard) consumeren
dezelfde geo_stack via dezelfde path-dependency.

**Volledige uitleg:** `docs/ARCHITECTURE.md` §3.

---

## 3. Harde regels (niet onderhandelbaar)

### 3.1 Skills vs plugins — strikte scheiding
- **Plugins** (`packages/lesa/lesa/plugins/`) doen analyse, bouwen
  claims/hypothesen, leveren artifacts.
- **Skills** (`C:\GIS_Projecten\geo_stack\geo_stack\skills\`) doen data-acquisitie,
  normalisatie, validatie.
- **Plugins importeren NOOIT** `requests`, `httpx`, `urllib3`, `owslib`
  of vergelijkbare HTTP-libs. Alle data-acquisitie via geo_stack-skills.
- **Skills weten niets** van LESA, hypothesen, rangorde, schaalniveau.

### 3.2 CRS
- **EPSG:28992 (RD New)** is de enige analyse-CRS.
- WGS84 alleen voor weergave (Folium is uit scope, dus eigenlijk
  alleen voor STAC search-pre-step).
- Elke plugin- en skill-output passeert `geo_stack.core.validate_rd_crs()`
  vóór persistentie.

### 3.3 Rangordemodel
Plugins declareren `rangorde_position` 1–7 (geologie → mens) in
`plugin.yaml`. Plugin-runs respecteren top-down volgorde. Overslaan
mag alleen met expliciete motivatie in `SkippedPlugin.reason`. Geen
stille bypass.

### 3.4 Reikwijdte-statement verplicht
Elke `PluginOutputs` bevat een `ScopeStatement` met `based_on`,
`not_tested`, `uncertainty_level`, `consequences`. Sessie-niveau
ScopeStatement wordt automatisch geaggregeerd. Geen export zonder
ScopeStatement.

### 3.5 Hypothese-structuur
Een `Hypothesis` zonder `falsifier` en `weakest_link` mag niet
gepersisteerd worden, behalve als `confidence_level=speculatief` —
dan mag `falsifier=None` met expliciete `reason_no_falsifier`-veld.
Documenteer deze uitzondering bij gebruik.

### 3.6 Geen Gemini, geen string-matching LLM-output
LLM-laag is **Anthropic Claude** (default `claude-sonnet-4-6`) via
de Anthropic SDK met **structured outputs / tool use**. Geen
Gemini-resten uit v1. Geen `if "fetch" in response.lower():`-patronen.

### 3.7 Output-scope
- **Geen interactieve HTML-viewers** (Folium/MapLibre).
- **Geen losse PNG/PDF als hoofd-output** behalve REGIS-doorsneden
  (matplotlib, omdat QGIS hier geen renderer voor heeft).
- Visuele review = QGIS Desktop via MCP.
- Hoofd-outputs: GeoPackage, COG, Parquet, JSON, QGIS-project,
  Markdown/Word rapport-secties.
- **QGIS-project is standaard output op alle schaalniveaus (1, 2, 3).**
  Markdown-rapport is aanvullend. Niveau 1 levert een beperkte lagenset
  (AHN, bodemkaart, AOI-grens) — snel in QGIS te openen.
- **Veldwerkprotocol-formaat: QField.** Output = `<sessie_id>_veldwerk.qfp`
  (QField project package) met meetlocaties, veldindicator-formulieren en
  hypothesen als leeslaag. Sync via QFieldCloud of USB.

### 3.8 Secrets
- `.env.example` met **lege defaults** in repo.
- Echte sleutels alleen in `.env` (gitignored).
- Geen API-keys in commit-history (controle vóór elke commit).

### 3.9 Tests
- Pakketnaam in `packages/<x>/<x>/` matcht imports — geen v1-style
  mismatch (`src.aoi` vs `pre_lesa.aoi`).
- Elke nieuwe plugin krijgt minimaal smoke-test in
  `plugins/<id>/tests/`.
- Skills hebben mock-fixtures (geen live HTTP in CI).

---

## 4. Wat je zelf mag besluiten

- Code-stijl binnen bestaande conventies (formatting via ruff/black,
  zie `pyproject.toml` bij implementatie).
- Refactor van geo_stack-modules — documenteer breaking changes in
  `CHANGELOG.md` (top-level).
- Nieuwe plugins voorstellen door **eerst een `plugin.yaml` voor
  review** te schrijven, daarna implementatie.
- Library-keuzes binnen Python-ecosysteem (geopandas, rasterio,
  pyogrio, shapely, pandas, numpy, xarray, dask, stackstac, httpx,
  pydantic v2, jinja2, python-docx).

---

## 5. Wat je NIET zelf besluit

- **Architecturale wijzigingen** t.o.v. `docs/ARCHITECTURE.md`. Stel
  voor in een nieuwe ADR (`docs/DECISIONS/00NN-<naam>.md`) en wacht
  op review.
- **Nieuwe data-bronnen** in `data_sources.yaml` (ex-`services.yaml`).
  Stel voor met endpoint, capabilities-check, en plek in catalogus.
- **Plugin-volgorde overrulen** zonder expliciete user-instructie.
- **Persistentie-keuze** wijzigen (lokaal-first hybride staat vast,
  zie ARCHITECTURE.md §2B).
- **Anthropic-model wisselen** zonder reden. Default = `claude-sonnet-4-6`.
  Voor zware orchestratie mag `claude-opus-4-7` voorgesteld worden.

---

## 6. Werkwijze per task-type

### 6.1 Nieuwe plugin bouwen
1. Schrijf `plugin.yaml` met metadata. Toon ter review.
2. Schets `Plugin.run()` interface (geen body) + verwachte
   PluginOutputs. Toon ter review.
3. Implementeer met smoke-test op Burgh-Haamstede AOI.
4. Voeg `.qml` styling toe in `styles/` met EW-huisstijl-defaults.
5. Documenteer in `docs/PLUGIN_AUTHORING.md` als nieuw patroon ontstaat.

### 6.2 geo_stack-skill toevoegen of refactoren
1. Lees bestaande skill (`C:\GIS_Projecten\geo_stack\skills\<naam>.md`).
2. Refactor met kleine commits + smoke-tests vóór functie-gedrag-
   wijziging.
3. Documenteer breaking changes in `CHANGELOG.md` met
   migratie-instructies.
4. Update `data_sources.yaml` als endpoint of capabilities veranderen.

### 6.3 Test-failures
- Run nooit `pytest --no-cov` of `--no-verify` om te omzeilen.
- Diagnostiseer root cause; herstel; opnieuw draaien.
- Bij flakey HTTP-mocks: vervang door fixtures met opgeslagen
  responses (zie `tests/fixtures/responses/`).

### 6.4 QGIS-MCP gebruik
- Roep MCP-tools aan via `mcp__qgis-mcp__*`-prefix.
- Plugin-outputs zijn altijd eerst files (gpkg/tif). MCP-stap is
  visuele toevoeging, niet data-stap.
- Bij MCP-fout: log + skip QGIS-stap; behoud sessie-state.
- Standaard layout-template:
  `C:\GIS_Projecten\qgis_mcp\Layout_templates\260407_Layout_a3_liggend.qpt`.

### 6.5 Burgh-Haamstede als testcase
- Briefing: `C:\GIS_Projecten\lesa-agent\LESA_Test_Burgh.md`
- Locatie: zandwinplas/ijsbaan, Burgh-Haamstede, Kop van Schouwen
- Geocoding: PDOK Locatieserver via `geo_stack.skills.kadaster`
  (let op — die is voor percelen; voor adres-geocoding gebruik
  `pdok_geocode` skill — toevoegen aan geo_stack indien nog niet
  aanwezig).
- AOI grenst aan N2000 Zeepeduinen — gebruik dit voor end-to-end
  test van `natura2000_nabijheid`-plugin.

---

## 7. Externe context die relevant is

### 7.1 Globale `C:\GIS_Projecten\CLAUDE.md`
Bevat PDOK-aanpak (Locatieserver vs WFS), PostgreSQL/PostGIS-
credentials, BRK-actualiteit, Kadaster-formaten. **Lees vóór elke
nieuwe data-fetch implementatie.**

### 7.2 PostgreSQL/PostGIS
Reeds beschikbaar (`postgresql-x64-18`, db `ewaarnemingen`). Voor
LESA optioneel als `PostgisSessionStore` backend. Credentials:
`C:\GIS_Projecten\.env` — laad **na** lokale `.env` zodat lokaal
override blijft werken.

### 7.3 PASTAS
Eigen project: `C:\GIS_Projecten\PASTAS\`. Adapter in
`packages/adapters/pastas_adapter/` mag PASTAS' venv niet uitlenen —
wel publieke API (PastaStore, ml.solve()). Documenteer adapter-
boundary expliciet.

### 7.4 v1 LESA referentie
`C:\GIS_Projecten\lesa-agent\` — referentie voor wat **niet** te doen
(zie OVERZICHT_LESA_AGENT.md §8 Don'ts). Niet over-mappen op v2.

### 7.5 Andere projecten
Bij twijfel over GIS-conventies: kijk naar `BeSI`, `Connectiviteit`,
`SMP_analyses` voor consistente stijl. Maar geen code copy-paste —
eerst evalueren of het in geo_stack past en daar centraliseren.

---

## 8. Conventies

### 8.1 Taal
- **Code-comments, docstrings, log-messages: Engels.**
- **Documentatie (`docs/`, `README.md`, ADR's): Nederlands** —
  Eelerwoude-context, NL-experts.
- **Plugin `description` veld: Nederlands** — leesbaar voor expert.
- **Git commit-messages: Nederlands** — consistent met collega's.

### 8.2 Bestandsnamen
- Python-modules: `snake_case`.
- Plugin-folders: `snake_case` matchend met `plugin.id`.
- `.qml` styles: `<doel>_<variant>.qml`, bv. `ahn_groen_rood_hillshade.qml`.
- Output-artifacts: `<plugin_id>__<output_name>.<ext>` (dubbele
  underscore als separator).

### 8.3 Coordinate Reference Systems in code
```python
RD = "EPSG:28992"  # nooit hardcoderen als 28992 zonder context
```

### 8.4 Type-hints verplicht
Pydantic v2 voor data-models, dataclasses voor lichte structs,
`typing.Protocol` voor extensibele interfaces. Geen `Any` zonder
`# noqa: ANY` + uitleg.

### 8.5 Logging
Gebruik `structlog` (of `logging`-module met JSON-formatter).
Geen `print()` in productie-paths. CLI-output mag `rich.print`.

---

## 9. Wat je niet hoort te doen

- **Geen interactieve HTML-output** (Folium/MapLibre). Out of scope.
- **Geen headless QGIS** (`qgis.core` standalone). Visualisatie via
  desktop-MCP.
- **Geen v1 (`pre_lesa/`) code overnemen** zonder expliciete review.
  Het is referentie, geen blueprint.
- **Geen string-matching op LLM-output**. Als je tool-use niet kan
  toepassen, escaleer naar user.
- **Geen PNG/PDF als hoofd-leverabel** behalve REGIS-doorsneden.
- **Geen pip-install in user's `.venv`** zonder bevestiging — gebruik
  `uv sync` op project-niveau.
- **Geen API-keys, .env, credentials in commits**. Pre-commit-hook
  (later) controleert dit, maar handmatige check eerst.

---

## 10. Bij twijfel

Stel vraag aan user. Briefing van Friso:

> *"Stel vragen als iets in de briefing onduidelijk is of conflicteert
> met wat je in de repo aantreft. Beter vooraf vragen dan verkeerd
> bouwen."*

Concrete signalen om vragen te stellen:
- Architectuur-conflict tussen briefing en bestaand `geo_stack`
- Methodologische ambiguïteit (rangordemodel-uitzonderingen)
- Data-bron-keuze tussen vergelijkbare alternatieven
- Output-formaat-keuze die niet expliciet in §3.7 staat
- Library-keuze met grote impact op afhankelijkheden

---

## 11. Documenten om te lezen vóór werk

1. `docs/ARCHITECTURE.md` — wat we bouwen en waarom
2. `C:\GIS_Projecten\lesa-agent\OVERZICHT_LESA_AGENT.md` — v1-leerschool
3. `C:\GIS_Projecten\lesa-agent\LESA_systeemanalyse.md` — methodologie
4. `C:\GIS_Projecten\lesa-agent\LESA_Test_Burgh.md` — testcase
5. `C:\GIS_Projecten\geo_stack\README.md` + `services.yaml` — data-laag
6. `C:\GIS_Projecten\CLAUDE.md` — globale GIS-conventies
