# LESA Agent v2 — Architectuurvoorstel

> **Status:** v0.1 voorstel ter review — feedback punten 1/2/3/6 verwerkt
> **Datum:** 2026-04-30
> **Auteur:** Claude Code (Sonnet 4.6) — verkenning op basis van briefing + repo
> **Reviewer:** Friso Schutten
> **Open:** punten 4 (niveau 1 output) en 5 (veldwerkprotocol app-format) — wacht op user-keuze

Dit document beschrijft de voorgestelde architectuur voor de LESA agentic
pipeline (v2), bouwend op de v1-leerschool (`OVERZICHT_LESA_AGENT.md`),
de bestaande `geo_stack` data-fetch tool, en het LESA-methodologisch
kader (`LESA_systeemanalyse.md`, OBN/LESA.INFO).

---

## 1. Repo-verkenning samenvatting

### 1.1 `geo_stack/` — beschikbare bouwsteen

**Locatie:** `C:\GIS_Projecten\geo_stack\`
**Karakter:** Skill-contract architectuur (Markdown contracten + Python
implementaties), centrale `services.yaml` registry, single-threaded
synchrone HTTP met retry-logica. Geen `pyproject.toml`, geen tests.

| Module | Rijpheid | Bruikbaarheid voor v2 |
|---|---|---|
| `geo_utils.py` | Productie-rijp | **Direct hergebruiken** (CRS-validatie, HTTP-sessie, BBOX-utils) |
| `discovery.py` | Productie-rijp | **Hergebruiken** — uitbreiden met TTL-cache op GetCapabilities |
| `bgt_fetcher.py` | Productie-rijp | **Hergebruiken** — async-wrapper toevoegen |
| `ahn_tiles.py` | Productie-rijp | **Hergebruiken** — LZW-compressie + nodata-handling toevoegen |
| `normalizer.py` | Productie-rijp | **Direct hergebruiken** (GeoParquet 1.1.0 schrijver, snake_case) |
| `kadaster.py` | Productie-rijp | **Hergebruiken** voor LESA-eigendomsanalyse |
| `provenance.py` | Productie-rijp | **Verplicht hergebruiken** (sidecar JSON, SHA256) — past op LESA reikwijdte-statement |
| `report.py` | Productie-rijp | Hergebruiken in CLI-laag |
| `cache.py` | Werkt fragiel | **Refactor:** atomic rename, thread-safe (zie §1.3) |
| `cloud_native.py` | Experimenteel | **Refactor:** http_timeout, ST_Intersects prefilter, retry-logica |
| `ndvi_stac.py` | Experimenteel | **Vervang** door `stackstac`-implementatie (lazy xarray + dask) |

**`data_sources.yaml`** (hernoemd van `services.yaml` in geo_stack — vóór
eerste commit doorvoeren) is de enige bron van endpoint-waarheid.
Geen endpoints hardcoderen in plugins.

**Kritiek wat moet vóór v2 productie gebruikt:**
1. Geen tests → smoke-tests per module + mock van services.yaml als fixture
2. Geen `pyproject.toml` → pakket niet installeerbaar in monorepo
3. Sync-only → blokkeert parallelle data-fetch (prioriteit voor snelheid)

### 1.2 v1 LESA (`pre_lesa/`) — referentie, geen blueprint

Bewaarde lessen (uit `OVERZICHT_LESA_AGENT.md` §8):

- **Bewaren:** Session-architectuur, AOI-parsing, Claim-dataclass met
  substantiation+uncertainty, Jinja2 voor rapport-secties.
- **Vervangen:** Gemini intent-string-matching → Claude tool use,
  test-pad-mismatch (`src.*` vs `pre_lesa.*`), BRO CPT als WMS (moet WFS).

### 1.3 QGIS-MCP (`qgis_mcp/`) — beschikbare integratie

Bestaande lokale MCP-server in `C:\GIS_Projecten\qgis_mcp\`. Levert tools
zoals `add_vector_layer`, `add_raster_layer`, `execute_processing`,
`get_layout_style`, `render_map`. Standaard layout-template:
`260407_Layout_a3_liggend.qpt` (EW-huisstijl). Beschikbaar als
`mcp__qgis-mcp__*` tools in dit project.

### 1.4 Niet aanwezig in repo (waar te ontwerpen)

- Geen `lesa-agent-v2/` directory — wordt nieuw aangemaakt
- Geen STAC-styling, geen `.qml`/`.sld` template-bibliotheek
- Geen PASTAS-integratie (PASTAS-project leeft elders, zie
  `C:\GIS_Projecten\PASTAS\`)

---

## 2. Drie afwegingen — keuze + motivatie

### A. Plugin-discovery: hybride (directory-scan + manifest)

**Keuze:** Directory-scan op `packages/lesa/lesa/plugins/*/plugin.py`
met een `Plugin` Protocol/dataclass die self-describes via class-attributes.

**Motivatie:**
- **Entry points (pyproject.toml):** Overkill in een monorepo waar
  packages via path-deps gekoppeld zijn. Voegt overhead toe (pip
  install -e bij elke nieuwe plugin) zonder voordeel.
- **Pure YAML registry:** Te statisch — laagste-waarde optie. Plugins
  zijn code, niet config; YAML-registry verdubbelt informatie en
  veroudert.
- **Directory-scan:** Snelste iteratie. Conventie boven configuratie.
  Plugin-folder = plugin. Geen registratie-stap. **Nadeel ondervangen:**
  een `lesa.plugins.registry` module bouwt bij import een dict
  `{plugin_id: PluginClass}` met validatie (uniek id, prerequisites
  bestaan, rangorde_position in 1..7). Faalt hard bij start als er
  duplicaten of cycles zijn.

Per plugin staat één `plugin.yaml` (manifest) **náást** de
implementatie — die bevat enkel **statische metadata** (id, naam,
omschrijving, rangorde, schaalniveaus, vereiste data-bronnen). Dit
laat de UI/agent metadata lezen zonder Python te importeren.

### B. Persistentie: lokaal-first hybride (GPKG + Parquet, PostGIS optioneel)

**Keuze:** Standaard lokaal: GeoPackage voor canonieke vector-outputs
+ Cloud-Optimized GeoTIFF voor rasters + Parquet voor tabulaire stats
+ JSON voor session-state. PostGIS optioneel als opt-in via
`config.yaml` voor team-/multi-user-context.

**Motivatie:**
- **PostGIS-only:** Te zware afhankelijkheid voor solo-gebruik
  (vereist server, credentials, netwerk). LESA-sessies zijn vaak
  per-project en eenmalig — een hele DB optuigen is overkill.
- **Lokaal-only:** Mist de natuurlijke samenwerkingslaag die PostGIS
  biedt voor gedeelde sessies (vooral in team-LESA's met meerdere
  experts).
- **Hybride:** Werkt direct out-of-the-box (geen DB nodig), maar
  ondersteunt PostGIS-backend via een `SessionStore` Protocol met
  twee implementaties (`LocalSessionStore`, `PostgisSessionStore`).
  Een sessie kan ook **geëxporteerd** worden naar PostGIS achteraf
  (use case: Burgh-Haamstede analyse delen met Eelerwoude-team).

**Concrete output-mapping:**
- `sessions/<session_id>/state.json` — sessie-state (AOI, hypothesen,
  scope statements)
- `sessions/<session_id>/data/<plugin_id>.gpkg|tif|parquet` — output
  per plugin, één file per plugin-run
- `sessions/<session_id>/qgis/<session_id>.qgz` — QGIS-project
- `sessions/<session_id>/styles/*.qml` — gebundelde stijlen
- `sessions/<session_id>/provenance/<plugin_id>.json` — sidecar
  metadata (hergebruik `geo_stack.provenance`)

### C. Geo_stack-skills vs LESA-plugins: strikte scheiding

**Keuze:** Skills = **data-laag** (acquisitie, normalisatie, validatie).
Plugins = **analyse-laag** (interpretatie, claims, hypothesen, kaarten).
Plugins mogen alleen via skills aan data komen; **geen directe HTTP**
in plugins.

**Motivatie:**
- **Testbaarheid:** Plugin-tests mocken de skill-laag. Skills hebben
  hun eigen integratie-tests tegen mock-services.
- **Herbruikbaarheid:** Een plugin als `bodemopbouw` werkt met dezelfde
  geo_stack-skill `bro_bodemkaart_fetcher`, ongeacht of die in LESA
  of in een ander project (BeSI, BKN-Alkmaar) draait.
- **Domein-grens:** Skills weten niets van LESA, hypothesen,
  rangordemodel of expert-judgement — die concepten leven in
  `lesa/`. Skills weten niets van schaalniveau.
- **Implementatie-regel:** een plugin importeert nooit `requests`,
  `httpx`, `urllib3`, `owslib` direct. Alle data-acquisitie loopt
  via `geo_stack.skills.<skill>.fetch(...)`. Linter regel of
  `import-policy` test.

**Uitzondering:** Plugins mogen wel direct met **lokale bestanden**
werken (uploads van waterschap-tijdreeksen, eigen veldnotities,
scan-data). Voor lokale I/O hoeft niet via geo_stack. Reden: data
die niet uit een service komt heeft geen acquisitie-laag.

---

## 3. Mappen-/package-structuur

```
lesa-agent-v2/
├── README.md                          # snelle intro + getting-started
├── CLAUDE.md                          # project-instructies voor Claude Code
├── pyproject.toml                     # workspace root (uv workspace)
├── uv.lock
├── .env.example                       # ANTHROPIC_API_KEY=, POSTGIS_URL=, lege defaults
├── .gitignore
├── CHANGELOG.md                       # breaking changes (vooral voor geo_stack)
├── docs/
│   ├── ARCHITECTURE.md                # dit document
│   ├── PLUGIN_AUTHORING.md            # hoe schrijf je een nieuwe plugin
│   ├── METHODOLOGY.md                 # rangordemodel, scope-statement, hypothesen
│   ├── DECISIONS/                     # ADR-style records voor architecturale keuzes
│   │   ├── 0001-plugin-discovery.md
│   │   ├── 0002-persistentie.md
│   │   └── 0003-skill-vs-plugin.md
│   └── DATA_SOURCES.md                # actuele PDOK/BRO/STAC/ESRI catalogus
├── packages/
│   ├── geo_stack/                     # opgenomen vanuit C:\GIS_Projecten\geo_stack
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── data_sources.yaml          # endpoint registry (hernoemd van services.yaml)
│   │   ├── geo_stack/                 # python pakket (was tools/)
│   │   │   ├── __init__.py
│   │   │   ├── core/                  # geo_utils, discovery, cache, normalizer
│   │   │   ├── skills/                # bgt, ahn, brp, kadaster, ndvi, bodem, regis ...
│   │   │   │   ├── ahn.py             # WCS + ESRI REST varianten
│   │   │   │   ├── bgt.py
│   │   │   │   ├── bro_bodemkaart.py
│   │   │   │   ├── bro_geomorfologie.py
│   │   │   │   ├── bro_regis.py       # nieuw — REGIS-doorsneden
│   │   │   │   ├── bro_grondwater.py  # nieuw — peilbuizen BRO
│   │   │   │   ├── ndvi_stac.py       # gerefactord met stackstac
│   │   │   │   ├── topotijdreis.py    # nieuw — historische kaarten ESRI REST
│   │   │   │   └── ...
│   │   │   ├── async_http.py          # nieuw — httpx + asyncio wrappers
│   │   │   ├── provenance.py
│   │   │   └── report.py
│   │   ├── docs/skills/               # markdown contracten per skill
│   │   └── tests/
│   ├── lesa/                          # LESA-specifieke laag
│   │   ├── pyproject.toml
│   │   ├── lesa/
│   │   │   ├── __init__.py
│   │   │   ├── session/               # sessie-state + persistentie
│   │   │   │   ├── state.py           # SessionState dataclass
│   │   │   │   ├── store.py           # SessionStore Protocol
│   │   │   │   ├── local_store.py     # LocalSessionStore (JSON+GPKG)
│   │   │   │   └── postgis_store.py   # PostgisSessionStore (opt-in)
│   │   │   ├── domain/                # kern-concepten
│   │   │   │   ├── aoi.py             # AOI + systeemgrens
│   │   │   │   ├── claim.py           # Claim dataclass
│   │   │   │   ├── hypothesis.py      # Hypothesis dataclass
│   │   │   │   ├── scope.py           # ScopeStatement dataclass
│   │   │   │   └── rangorde.py        # rangorde-volgorde + validatie
│   │   │   ├── plugins/               # analyse-modules
│   │   │   │   ├── _base.py           # Plugin Protocol/ABC
│   │   │   │   ├── _registry.py       # directory-scan + validatie
│   │   │   │   ├── ahn_relief/
│   │   │   │   │   ├── plugin.yaml    # statische metadata
│   │   │   │   │   ├── plugin.py      # implementatie
│   │   │   │   │   ├── styles/        # *.qml/*.sld voor de output
│   │   │   │   │   └── tests/
│   │   │   │   ├── bodemopbouw/
│   │   │   │   ├── peilbuizen_pastas/
│   │   │   │   ├── geomorfologie/
│   │   │   │   ├── historisch_landgebruik/
│   │   │   │   ├── natura2000_nabijheid/
│   │   │   │   └── systeemgrens_voorstel/
│   │   │   ├── agent/                 # Claude orchestratie
│   │   │   │   ├── orchestrator.py    # plugin-selectie via tool use
│   │   │   │   ├── tools.py           # Anthropic tool definities (per plugin één tool)
│   │   │   │   ├── prompts.py         # system prompts (rangordemodel, scope, hypothesen)
│   │   │   │   └── synthesis.py       # plugin-outputs → hypothese-voorstellen
│   │   │   ├── report/                # rapport-generatie
│   │   │   │   ├── jinja_engine.py
│   │   │   │   ├── docx_export.py     # python-docx
│   │   │   │   └── templates/         # .md.j2 sectie-templates
│   │   │   ├── qgis/                  # QGIS-MCP integratie
│   │   │   │   ├── mcp_client.py      # roept mcp__qgis-mcp__* aan
│   │   │   │   ├── styling.py         # .qml application
│   │   │   │   └── layout.py          # 260407_Layout_a3_liggend.qpt
│   │   │   ├── outputs/               # output-strategieën per gekozen leverabel
│   │   │   │   ├── _base.py           # OutputStrategy Protocol
│   │   │   │   ├── veldwerkprotocol.py
│   │   │   │   ├── bureau_lesa.py
│   │   │   │   ├── qgis_project.py
│   │   │   │   ├── markdown_report.py
│   │   │   │   ├── word_report.py
│   │   │   │   └── hypothesis_export.py
│   │   │   └── cli/
│   │   │       ├── main.py
│   │   │       └── commands.py
│   │   ├── config/
│   │   │   ├── default.yaml           # default settings
│   │   │   └── styles/                # default .qml per laagtype
│   │   └── tests/
│   └── adapters/                      # externe-tool adapters
│       ├── pastas_adapter/            # PASTAS wrapper voor peilbuizen-plugin
│       └── menyanthes_export/         # csv-format voor Menyanthes
├── examples/
│   ├── burgh_haamstede/               # de testcase
│   │   ├── README.md
│   │   ├── briefing.md                # uit LESA_Test_Burgh.md
│   │   └── aoi.geojson
│   └── lesa_systeemanalyse_referentie.md
└── scripts/
    ├── new_plugin.py                  # template scaffolding
    └── validate_plugins.py            # CI-check
```

**Kerngedachte:**
- **`C:\GIS_Projecten\geo_stack\`** = domein-neutrale data-laag, los
  project, geconsumeerd via path-dependency (herbruikbaar buiten LESA,
  naar BeSI/BKN/Connectiviteit).
- **`packages/lesa/`** = alle LESA-specifieke logica.
- **`packages/adapters/`** = externe tools die niet binnen geo_stack of
  LESA passen (PASTAS, Menyanthes-export). Bewust gescheiden zodat
  PASTAS' eigen levenscyclus geen impact heeft op LESA-core.

---

## 4. Plugin-interface

### 4.1 `plugin.yaml` (statische metadata)

```yaml
# packages/lesa/lesa/plugins/ahn_relief/plugin.yaml
id: ahn_relief
name: "AHN reliëf-analyse"
description: "Hoogte, hellingen, lokale reliëf-amplitude en stroomgebied-afleiding uit AHN4."
version: "0.1.0"
rangorde_position: 2          # geomorfologie
scale_levels: [1, 2, 3]       # bruikbaar op alle drie niveaus
landscape_types: [all]        # geldig voor alle landschapstypen
prerequisites: []             # geen voorgaande plugin nodig
data_sources:                 # welke geo_stack-skills geraadpleegd
  - skill: ahn
    required: true
optional_inputs:
  - name: vergelijkings_periode
    type: enum
    values: [AHN3, AHN4]
    default: AHN4
outputs:
  - kind: raster
    name: dtm
    crs: 28992
  - kind: raster
    name: hillshade
  - kind: vector
    name: stroomgebieden
  - kind: stats
    name: relief_summary
produces_claims: true
produces_hypotheses: true
qgis_styles:
  - target: dtm
    qml: styles/ahn_groen_rood_hillshade.qml
  - target: stroomgebieden
    qml: styles/stroomgebieden_polyline.qml
```

**`landscape_types`** accepteert een lijst van:
`all`, `beekdal`, `duinen`, `veen`, `zandlandschap`, `klei`.
De waarde `all` betekent dat de plugin voor elk landschapstype
geldig is. De registry filtert plugins bij sessie-start op basis
van `SessionState.landscape_type`. Plugins met type-specifieke
defaults (bijv. `peilbuizen_pastas` met andere modeltypen voor
veen vs. zand) declareren hun type expliciet en overschrijven
de defaults per landschapstype via een optioneel `defaults_per_landscape`
blok (uitwerking later).

### 4.2 Python-interface (Protocol/ABC sketch)

```python
# packages/lesa/lesa/plugins/_base.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from pathlib import Path
from pydantic import BaseModel
from lesa.domain import Claim, Hypothesis, ScopeStatement
from lesa.session import SessionContext

# --- Getypeerde params (punt 1) ---

class PluginParams(BaseModel):
    """Basis voor plugin-specifieke params.

    Elke plugin definieert een subclass, bijv.:
        class AhnReliefParams(PluginParams):
            vergelijkings_periode: Literal["AHN3", "AHN4"] = "AHN4"

    De subclass wordt automatisch vertaald naar JSON Schema via
    Plugin.params_schema() en meegegeven aan de run_plugin-tool
    definitie. Dit garandeert dat Claude nooit ongeldige params
    injecteert — de tool call faalt by construction als params
    het schema schenden.
    """
    pass

@dataclass
class PluginInputs:
    aoi: "AOI"                          # bestuurlijke grens
    systeemgrens: "AOI | None"          # optioneel verfijnde grens
    scale_level: int                    # 1, 2, of 3
    user_params: PluginParams           # getypeerd — geen vrije dict
    workspace: Path                     # sessie-werkfolder

@dataclass
class PluginRawData:
    """Tussenstap: data opgehaald in fetch_data(), klaar voor analyze()."""
    datasets: dict[str, "GeoDataFrame | Path"]  # per skill-naam

@dataclass
class PluginOutputs:
    artifacts: dict[str, Path]          # {"dtm": "...tif", "stroomgebieden": "...gpkg"}
    stats: dict[str, dict]              # {"relief_summary": {...}}
    claims: list[Claim]
    hypotheses: list[Hypothesis]
    scope_statement: ScopeStatement     # verplicht — zie §3.4 briefing
    qgis_layers: list["QgisLayerSpec"]  # wat QGIS-MCP moet inladen + welke style

@runtime_checkable
class Plugin(Protocol):
    """Plugin contract — twee fasen (punt 2, optie B).

    Fase 1: fetch_data() is async — orchestrator roept dit voor alle
            geplande plugins parallel aan via asyncio.gather().
    Fase 2: analyze() is sync — sequentieel, na alle fetches klaar.

    Reden voor optie B i.p.v. volledig async:
    - Zware PASTAS-berekeningen zijn synchrone pandas/numpy-code;
      die in een async context draaien via run_in_executor voegt
      alleen overhead toe.
    - Parallellisme is zinvol bij I/O (HTTP), niet bij CPU-werk.
    - Scheiding maakt mocking in tests eenvoudiger: mock fetch_data(),
      test analyze() puur deterministisch.
    """

    META_PATH: Path                     # auto-set door registry; pad naar plugin.yaml

    @classmethod
    def params_schema(cls) -> dict:
        """Geef JSON Schema terug voor de plugin-specifieke params.

        Wordt gebruikt om de run_plugin-tool definitie te genereren —
        Claude krijgt zo schema-gevalideerde params mee.
        Implementatie: return cls.Params.model_json_schema()
        """
        ...

    def validate_inputs(self, inputs: PluginInputs) -> list[str]:
        """Return list of error messages; lege lijst = OK."""

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        """Haal data op via geo_stack-skills (async, paralleliseerbaar).

        Geen analyse hier — alleen acquisitie en opslaan naar workspace.
        Geen directe HTTP-calls: alles via geo_stack.skills.<skill>.fetch().
        """

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        """Voer de analyse uit op de opgehaalde data (sync, deterministisch).

        Geen netwerk-I/O. Input is altijd local (workspace-paden of in-memory).
        """
```

### 4.2.1 Orchestrator async-flow (punt 2 vervolg)

```python
# agent/orchestrator.py — pseudo
async def run_plugins(session, plugin_ids):
    plugins = [registry[pid] for pid in plugin_ids]

    # Fase 1: alle fetch_data's parallel
    raw_data_list = await asyncio.gather(
        *[p.fetch_data(build_inputs(session, p)) for p in plugins],
        return_exceptions=True,
    )

    # Fase 2: analyze sequentieel (respecteert rangorde-volgorde)
    for plugin, raw in zip(plugins, raw_data_list):
        if isinstance(raw, Exception):
            session.mark_failed(plugin.id, raw)
            continue
        outputs = plugin.analyze(build_inputs(session, plugin), raw)
        session.record_outputs(plugin.id, outputs)
```

**Gevolg voor geo_stack:** alle skills in `geo_stack/skills/` krijgen
een async variant via `async_http.py` (httpx + asyncio). De sync-varianten
blijven bestaan voor gebruik buiten de agent-context (scripts, Jupyter).

### 4.3 Registry

```python
# packages/lesa/lesa/plugins/_registry.py — pseudo
def discover_plugins(plugins_dir: Path) -> dict[str, type[Plugin]]:
    registry = {}
    for plugin_dir in plugins_dir.iterdir():
        if not (plugin_dir / "plugin.yaml").exists():
            continue
        meta = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
        module = importlib.import_module(f"lesa.plugins.{plugin_dir.name}.plugin")
        cls = getattr(module, "Plugin")
        registry[meta["id"]] = cls
    _validate(registry)  # uniek id, prerequisites bestaan, geen cycles
    return registry
```

### 4.4 Rangordemodel-afdwinging

```python
# packages/lesa/lesa/domain/rangorde.py — pseudo
RANGORDE = {
    1: "geologie",
    2: "geomorfologie",
    3: "bodem",
    4: "hydrologie",
    5: "vegetatie",
    6: "fauna",
    7: "mens",
}

def can_run(plugin_meta, session_state) -> tuple[bool, str]:
    higher_levels = [r for r in RANGORDE if r < plugin_meta["rangorde_position"]]
    completed_or_skipped = {p["rangorde_position"]
                            for p in session_state.plugin_runs
                            if p["status"] in {"completed", "skipped_with_reason"}}
    missing = [r for r in higher_levels if r not in completed_or_skipped]
    if missing:
        return False, (f"Hogere-orde modules nog niet gedraaid: "
                       f"{[RANGORDE[r] for r in missing]}. "
                       f"Sla expliciet over met motivatie of voer ze eerst uit.")
    return True, ""
```

UX-gevolg:
- CLI weigert default plugins die rangorde overslaan.
- `--skip-rangorde-check --reason "..."` flag dwingt forced run en
  registreert reden in session_state.
- Agent prompt bevat instructie: kies niet over rangorde heen zonder
  motivatie aan de gebruiker te vragen.

---

## 5. Drie voorbeeldplugins (interface-niveau)

### 5.1 `ahn_relief`

```yaml
id: ahn_relief
rangorde_position: 2
scale_levels: [1, 2, 3]
landscape_types: [all]
data_sources:
  - skill: ahn                # WCS PDOK + ESRI REST hillshade-image
  - skill: ahn_esri_rest      # ESRI dynamic tile voor mooie groen-rood styling
prerequisites: []
```

**Inputs:** AOI/systeemgrens, scale_level (bepaalt resolutie: 5m@1,
0.5m@3), optionele AHN-versie keuze.
**Outputs:** `dtm.tif` (LZW-gecomprimeerd COG), `hillshade.tif`,
`stroomgebieden.gpkg` (afgeleid via QGIS Processing `r.watershed` of
`whitebox`), `relief_summary` (min/max/range per stroomgebied).
**Claims:** "Het reliëf binnen AOI varieert van X tot Y mNAP, mediaan
Z." — substantiation: AHN4 percentielen, reference: PDOK AHN4 v2026.
**Hypothesen:** Lokale dalvormige depressies (>2m onder omgevings­
mediaan) → hypothese kwellocatie als stap voor hydrologie-plugin.
**QGIS styling:** `ahn_groen_rood_hillshade.qml` — gestapeld DTM met
colorramp + 70%-transparante hillshade erover; standaardlegende.
**Scope statement:** "Gebaseerd op AHN4 v2026 (cyclus 5m); standplaats­
schaal vereist ahn_05m fetch — niet uitgevoerd indien scale_level≤2."

### 5.2 `peilbuizen_pastas`

```yaml
id: peilbuizen_pastas
rangorde_position: 4              # hydrologie
scale_levels: [2, 3]              # niet zinvol op niveau 1
landscape_types: [all]            # geldig voor alle typen; defaults verschillen
prerequisites: [ahn_relief]       # nodig voor MV-koppeling
data_sources:
  - skill: bro_grondwater         # BRO peilbuizen + tijdreeksen
  - skill: knmi_neerslag          # neerslag-stations binnen 5km
  - skill: knmi_makkink           # referentieverdamping
optional_inputs:
  - name: model_typen
    type: list
    values: [linear, recharge, well, river]
    default: [linear, recharge]   # override in defaults_per_landscape voor veen
  - name: warmup_jaren
    type: int
    default: 3
defaults_per_landscape:
  veen:
    model_typen: [recharge, well]  # drempelresponsie beter voor veen
  duinen:
    model_typen: [linear, recharge]
```

**Inputs:** AOI/systeemgrens, AHN-DTM voor MV-bepaling, optionele
extra peilbuis-IDs (naast BRO-default), optionele meetnet-data van
waterschap.
**Outputs:** `peilbuizen.gpkg` (locaties + metadata),
`tijdreeksen.parquet` (raw observaties), `pastas_modellen.json`
(per peilbuis een **set** kandidaat-modellen met diagnostiek), per
peilbuis één `<bro_id>.pas` PASTAS-modelbestand,
`menyanthes_export.csv`, `hydromonitor_export.csv`.
**Claims:** "Peilbuis B12A0123 vertoont seizoenamplitude 0.8m,
GLG-2.1m, GHG-1.3m; lineair recharge-model verklaart 87% (R²)."
**Hypothesen:** "Sterke positieve trend (>5cm/jaar) in B12A0123
suggereert verstoring; mogelijk veroorzaakt door peilverlaging
ijsbaan." — falsifier: identieke trend in onverstoorde reference­
buizen elders. confidence_level: plausibel. weakest_link:
referentiebuis-keuze.
**Geen automatische winner:** Plugin levert kandidaten + diagnostiek.
Expert kiest in Hydromonitor/Menyanthes welke modellen geldig zijn.
**Scope statement:** "Tijdreeksanalyse op alleen BRO-peilbuizen
(geen waterschap-meetnet); alleen historie t/m 2026-04-30; geen
stationariteits­toets toegepast — door expert te valideren."

### 5.3 `bodemopbouw`

```yaml
id: bodemopbouw
rangorde_position: 3              # bodem (na geomorfologie)
scale_levels: [1, 2, 3]
landscape_types: [all]
prerequisites: [geomorfologie]    # bodem volgt op geomorfologie
data_sources:
  - skill: bro_bodemkaart         # 1:50.000 bodemkaart vector
  - skill: bro_regis              # REGIS hydrogeologische lagen
  - skill: bro_geotop             # GEOTOP voxel-data
optional_inputs:
  - name: regis_doorsneden
    type: list                    # lijst van LineString-WKT's
    default: [auto]               # auto = N-Z + W-O door centroid
```

**Inputs:** AOI/systeemgrens, vooraf gedraaide geomorfologie-output
(voor context-koppeling), optionele expert-getekende doorsneden.
**Outputs:** `bodemkaart.gpkg` (clip op AOI),
`regis_doorsnede_<naam>.png` + `.gpkg` (2D-profiel-export),
`geotop_voxels.parquet` (niveau 3 alleen), `bodem_samenvatting`
(klasse-aandelen ha + %).
**Claims:** "Dominant bodemtype binnen AOI: kalkhoudende
duinvaaggrond (62%, 31 ha); secundair: kalkloze duinvaaggrond (18%)."
**Hypothesen:** "Combinatie van diepe doorlatende zandlagen (REGIS
laag1) en ondiepe slecht-doorlatende veenrest (REGIS laag3) → mogelijke
schijngrondwaterspiegel; hypothese voor hydrologie-plugin."
**QGIS styling:** `bodemkaart_categorical.qml` met BRO-officiele
kleuren, REGIS-doorsnede als matplotlib-PNG (geen QGIS-renderer voor
2D-profielen).
**Scope statement:** "Bureaustudie op BRO-vlakken 1:50.000; geen
veldboring; voor lokale interpretatie standplaats­schaal aanvullen
met veld­profiel."

---

## 6. Agent-orchestratie schets

### 6.1 Architectuur

```
┌─────────────────────────────────────────────────────────────┐
│                    LESA Agent (Claude)                      │
│  Model: claude-sonnet-4-6 (default)                         │
│  Mode: tool use met structured outputs                      │
└──────────────┬──────────────────────────────────────────────┘
               │
               │ kiest tools op basis van:
               │   1. user-vraag
               │   2. session_state (welke plugins gedraaid?)
               │   3. rangorde-volgorde (top-down)
               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Tool catalog                            │
│  - load_aoi(geojson | wkt | name)                           │
│  - propose_systeemgrens()           ← speciale meta-plugin  │
│  - run_plugin(plugin_id, params)    ← één tool per plugin? Nee, één generieke tool met enum │
│  - skip_plugin(plugin_id, reason)                           │
│  - propose_hypothesis(text, supporting_claim_ids, ...)      │
│  - export_session(strategy_id)      ← veldwerkprotocol etc. │
│  - get_session_state()                                      │
│  - render_qgis_layer(plugin_id, output_name)                │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Tool-design principes

- **Eén generieke `run_plugin` tool** met `plugin_id` als enum-parameter
  (gegenereerd uit registry op startup). Reden: scaalt naar 20+ plugins
  zonder Claude's tool-list te overspoelen. Claude krijgt plugin-
  metadata via `list_plugins()` als die niet in system prompt past.

- **Typed params via JSON Schema (punt 1 feedback):** het `params`-veld
  in de `run_plugin`-tool is **niet** een vrije dict. Bij startup
  genereert de orchestrator de tool-definitie dynamisch met het JSON
  Schema van elke plugin:
  ```python
  # agent/tools.py — pseudo
  def build_run_plugin_tool(registry):
      plugin_schemas = {
          pid: cls.params_schema()   # via PluginParams.model_json_schema()
          for pid, cls in registry.items()
      }
      return {
          "name": "run_plugin",
          "input_schema": {
              "type": "object",
              "properties": {
                  "plugin_id": {"type": "string", "enum": list(registry)},
                  "params": {
                      "oneOf": [
                          {"if": {"properties": {"plugin_id": {"const": pid}}},
                           "then": schema}
                          for pid, schema in plugin_schemas.items()
                      ]
                  }
              },
              "required": ["plugin_id", "params"]
          }
      }
  ```
  Claude kan zo nooit een ongeldige param meegeven — de tool call
  faalt by construction vóór de plugin-code wordt bereikt.

- **Structured outputs**: elke tool returnt JSON met expliciete
  schema's. Geen vrije tekst-parsing.
- **Tool use loop in `agent/orchestrator.py`** met expliciete max_iters
  (default 30) en cost-cap.

### 6.3 Top-down volgorde-handhaving

In de system prompt:

> **Rangordemodel (verplicht).** Plan plugin-runs in volgorde
> geologie → geomorfologie → bodem → hydrologie → vegetatie →
> fauna → mens. Als de gebruiker direct vraagt om bv. een
> hydrologie-plugin terwijl bodem niet gedraaid is, **wijs niet
> stilzwijgend aan**: leg uit dat bodem eerst nodig is, en bied
> aan om hem mee te draaien of expliciet over te slaan met
> motivatie.

Plus harde guard in `run_plugin`-tool:
- pre-check via `rangorde.can_run()`
- weigert run met instructieve fout-respons → Claude leest dat en
  stelt corrigerende plan voor

### 6.4 Hypothese-synthese

Na elke plugin-run roept de agent `propose_hypothesis` aan met:
- `supporting_claims`: claim-IDs uit deze run + eerder
- `weakest_link`: zwakste schakel in de keten
- `falsifier`: wat zou de hypothese ontkrachten

Reden voor expliciete tool: dwingt structuur af; voorkomt dat
hypothesen in vrije rapport-tekst verstopt raken.

### 6.5 System prompt-skelet (high level)

```
Rol: LESA-bureauondersteuner. Niet de eindverantwoordelijke expert.

Werkwijze:
1. Ontleed user-vraag in AOI + scale_level + gewenste outputs.
2. Plan plugin-volgorde top-down (rangordemodel).
3. Voer plugins één voor één uit; reflecteer na elke run.
4. Stel hypothesen voor met expliciete falsifiers en zwakke schakels.
5. Bewaar reikwijdte-statements per plugin én sessie-niveau.
6. Bij twijfel: stel vraag aan expert. Vermijd auto-keuzes voor
   zaken die expert-judgement vereisen (model-keuze, validatie,
   weging concurrerende hypothesen).

Hard rules:
- Geen plugin-run die rangorde-volgorde schendt zonder expliciete
  skip-motivatie.
- Geen claim zonder bron en onzekerheidsniveau.
- Geen hypothese zonder falsifier en weakest_link.
- Geen output-export zonder ScopeStatement.
```

---

## 7. Sessie-state schema

```python
# packages/lesa/lesa/session/state.py — pseudo (Pydantic v2 of dataclass-json)

@dataclass
class SessionState:
    # Identiteit
    session_id: str                       # ULID
    project_name: str                     # "Burgh-Haamstede ijsbaan"
    created_at: datetime
    updated_at: datetime

    # Geografie
    aoi: AOI                              # bestuurlijke grens (uit briefing/GeoJSON)
    systeemgrens: AOI | None              # voorgesteld door systeemgrens-plugin, accepted door expert
    aoi_source: str                       # "user_geojson" | "geocode:burgh-haamstede" | ...

    # Methodologie
    scale_level: Literal[1, 2, 3]
    landscape_type: str | None             # "duinen" | "beekdal" | "veen" | "zandlandschap" | "klei" | None
    chosen_outputs: list[OutputStrategyId]   # ["veldwerkprotocol", "qgis_project"]

    # Planning + uitvoering
    plugin_runs: list[PluginRun]          # geordend; elk met status, params, artifact-paden
    skipped_plugins: list[SkippedPlugin]  # plugin_id + reden + timestamp

    # Inhoudelijke output
    claims: list[Claim]                   # alle claims uit alle plugins
    hypotheses: list[Hypothesis]
    scope_statements: list[ScopeStatement]  # per plugin + één sessie-overarchend

    # Operatie-metadata
    agent_history: list[AgentTurn]        # tool calls + responses (truncated)
    cost_tracking: CostInfo               # input/output tokens, EUR-schatting
    config_snapshot: dict                 # gefroren config bij start (data_sources.yaml hash)


@dataclass
class PluginRun:
    plugin_id: str
    plugin_version: str
    status: Literal["queued", "running", "completed", "failed", "skipped"]
    inputs: dict                          # serialized PluginInputs
    artifacts: dict[str, Path]
    started_at: datetime
    completed_at: datetime | None
    duration_s: float | None
    error: str | None
    provenance_path: Path                 # naar geo_stack.provenance JSON


@dataclass
class Hypothesis:
    id: str
    proposed_mechanism: str
    predicted_observation: str
    falsifier: str
    confidence_level: Literal["sterk_onderbouwd", "plausibel", "speculatief"]
    weakest_link: str
    supporting_claims: list[str]          # claim-IDs
    status: Literal["voorgesteld", "actief", "getoetst_bevestigd",
                    "getoetst_verworpen", "bijgesteld"]
    field_protocol: FieldProtocolStub | None  # gekoppelde meetlocatie + indicatoren


@dataclass
class ScopeStatement:
    scope: Literal["plugin", "session"]
    subject_id: str                       # plugin_id of "session"
    based_on: list[str]                   # ["AHN4 v2026", "BRO Bodemkaart 1:50000"]
    not_tested: list[str]                 # ["veldverificatie", "stationariteit"]
    uncertainty_level: Literal["laag", "middel", "hoog"]
    consequences: str                     # vrij tekstveld — gevolgen van scope-keuze
```

**Persistentie-mapping** (LocalSessionStore):
- `state.json`: serializatie van `SessionState` (ZIP-compressed bij groei)
- `data/<plugin_id>/`: artifacts (gpkg/tif/parquet)
- `provenance/<plugin_id>.json`: sidecar metadata
- `qgis/<session_id>.qgz`: gegenereerd QGIS-project
- `report/<output_strategy>.{md,docx}`: gegenereerd rapport

**Idempotentie:** elke plugin-run schrijft naar `data/<plugin_id>/v<version>/`
zodat re-runs tracked blijven.

---

## 8. QGIS-MCP integratie

### 8.1 Welk MCP-pakket

**`mcp__qgis-mcp__*`** — al beschikbaar in dit project (zie tools-lijst).
Server in `C:\GIS_Projecten\qgis_mcp\`. Gebruik:

- `add_vector_layer(path, name, style)`
- `add_raster_layer(path, name, style)`
- `execute_processing(algorithm, params)` — bv. `r.watershed`,
  `gdal:slope`
- `get_layout_style(template)` — voor huisstijl-template
- `render_map(layout_name, output_path)` — print PDF

### 8.2 Werkwijze

**Niet-exclusief co-werken met expert:**
- Expert opent eigen QGIS-instantie (Desktop) met MCP-server
  ingeschakeld.
- LESA-agent voegt lagen toe via `add_*_layer` calls.
- Expert mag intussen handmatig lagen toevoegen, bewerken,
  verschuiven — agent merkt dat via `get_project_info()` polling
  niet, maar dat is bewust: agent **suggereert toevoegingen**, expert
  is eigenaar van het project.

**Implementatie-laag:** `lesa/qgis/mcp_client.py` is een thin wrapper
die:
1. Plugin output ontvangt (`PluginOutputs.qgis_layers`)
2. Voor elke layer-spec roept `add_*_layer` met juiste pad + style
3. Past styling toe via `.qml` uit `plugin/styles/`
4. Optioneel: roep `get_layout_style` voor huidige template, en
   `render_map` voor PDF-export aan einde van sessie

**Layout-template:** standaard `260407_Layout_a3_liggend.qpt`
(EW-huisstijl, kleuren `rgb(56,56,58)` + `rgb(144,143,71)`, Calibri).
LESA-agent past geen layouts zelf aan — alleen lagen toevoegen
en stijl koppelen. Layout-bewerking blijft expert-handwerk.

### 8.3 Headless QGIS expliciet uitgesloten

Plugins genereren outputs (gpkg/tif) los van QGIS — die zijn
QGIS-onafhankelijk. **Alle visualisatie via desktop-QGIS over MCP.**
Geen `qgis-bin --process`-aanroepen, geen PyQGIS standalone.
Reden: visuele review door expert is essentieel, headless rendering
mist de iterative loop.

### 8.4 Styling-bibliotheek

Per plugin staan `.qml`'s in `plugins/<id>/styles/`. Daarnaast
project-default styles in `packages/lesa/config/styles/` voor:
- `vector_categorical_default.qml`
- `vector_graduated_default.qml`
- `raster_continuous_groen_rood.qml`
- `aoi_outline.qml`
- `systeemgrens_outline.qml`

**Cartografische principe:** elke plugin levert een visueel
publicatie-klare default. Expert kan over-rulen, maar zonder werk
ziet output er al EW-huisstijl-conform uit.

---

## 9. Risico's & open vragen

### 9.1 Risico's

1. **STAC/NDVI-implementatie blijft fragiel**
   - geo_stack heeft skelet-implementatie, vervangen door `stackstac`
     vereist memory/dask-tuning en nieuwe afhankelijkheden.
   - **Mitigatie:** los van LESA-MVP houden; maak NDVI-plugin
     `vegetatie_ndvi_trend` als latere plugin (na Burgh-Haamstede
     scope).

2. **PASTAS-koppeling complex**
   - PASTAS heeft eigen project-structuur (`C:\GIS_Projecten\PASTAS\`)
     met PastaStore. Adapter moet zonder PASTAS' project-deps werken.
   - **Mitigatie:** `packages/adapters/pastas_adapter/` als isolatielaag;
     overweeg PASTAS optioneel te installeren via extras.

3. **QGIS-MCP server-stabiliteit**
   - MCP draait lokaal in expert's QGIS — als die crasht of niet
     draait, faalt agent-output-stap.
   - **Mitigatie:** plugin-outputs zijn eerst altijd files
     (gpkg/tif), QGIS-stap is laatste niet-essentiële laag. Bij
     MCP-fout: log + skip QGIS-stap, behoud rest van sessie.

4. **Anthropic API kosten bij lange sessies**
   - Tool-use-loop met 20+ plugins kan veel tokens kosten (vooral
     als grote stats/claim-blokken in context terugkomen).
   - **Mitigatie:** `cost_tracking` in SessionState; truncate
     `agent_history` in context-window; gebruik prompt caching.

5. **Rangorde-handhaving voelt rigide**
   - In praktijk maken experts soms shortcuts (eerst hydrologie
     bekijken om te beslissen of bodem-detail nodig is).
   - **Mitigatie:** skip-met-motivatie is een eerste-klas pad,
     niet een uitzondering. Documentatie benadrukt
     "rangordemodel = werkvolgorde, niet dogma".

### 9.2 Open vragen voor review

**Verwerkt op basis van feedback (hoeven niet meer beantwoord):**

- ~~**run_plugin params als ongestructureerde dict**~~ — opgelost: typed
  `PluginParams` (Pydantic) + JSON Schema per plugin in tool-definitie (§4.2, §6.2).
- ~~**async/sync conflict in plugin-interface**~~ — opgelost: tweefasen-aanpak
  (`fetch_data` async, `analyze` sync) met parallel gather in orchestrator (§4.2.1).
- ~~**landscape_types ontbrak**~~ — opgelost: toegevoegd aan `plugin.yaml` +
  `SessionState` + `defaults_per_landscape` blok voor type-specifieke defaults (§4.1, §7).
- ~~**`services.yaml` hernoemen**~~ — besloten: hernoemd naar `data_sources.yaml`
  door het hele document en te doen vóór eerste commit in geo_stack.

---

**Besloten op basis van user-feedback:**

- **Niveau 1 outputs:** QGIS-project is standaard output op **alle** schaalniveaus
  (1, 2, 3). Markdown-rapport is aanvullend, niet vervangend. Niveau 1 expert opent
  het QGIS-project voor oriëntatie — de beperkte lagenset (AHN, bodemkaart, AOI)
  maakt dit bruikbaar zonder zware setup.

- **Veldwerkprotocol formaat:** **QField** — open source, GPKG-gebaseerd, leest
  het QGIS-project direct. Veldwerkprotocol-output is een QField-klaar package:
  `<sessie_id>_veldwerk.qfp` (QField project package) met meetlocaties als
  puntlaag + formulieren voor veldindicatoren + leeslaag van LESA-hypothesen
  als context. Expert synct via QFieldCloud of handmatige USB-transfer.

---

**Nog open — inhoudelijk:**

3. **Naamgeving package `lesa`** — botst die met Python-packages elders?
   Alternatief: `lesa_core`. Voorkeur?

4. **`uv` als build/dependency-tool** — bevestig dat dit de gewenste keuze
   is. Alternatief: poetry of plain `pip-tools`.

5. **Hypothese-falsifier-verplichting** — voor speculatieve hypothesen
   is een falsifier soms niet goed te formuleren. Toestaan dat
   `falsifier` optioneel is bij `confidence_level=speculatief`?

6. **Multi-AOI sessies** — architectuur nu: één AOI + één systeemgrens.
   Multi-systeem-grens vergelijking: v0 of latere uitbreiding?

7. **Burgh-Haamstede CI-test** — als reference-test: live PDOK of
   opgeslagen fixtures? (Live = realistischer; fixtures = CI-stabiel.)

8. **Word-export startpunt** — python-docx met `.dotx` template of
   pandoc? Welke EW-huisstijl-template als basis?

9. **Subsetting per scale_level** — voorstel: skill is dom (parameter),
   plugin mapt `scale_level → resolutie`. Akkoord?

---

## 10. Volgende stap

Na review van dit document:

1. ADR's (`docs/DECISIONS/000{1,2,3}.md`) vastleggen op basis van §2.
2. Monorepo opzetten (`pyproject.toml` workspace, `geo_stack` ↔ `lesa`
   ↔ `adapters`).
3. `geo_stack` hardenings: pyproject.toml + smoke-tests + thread-safe
   cache + STAC-refactor (in volgorde van prioriteit).
4. Eén plugin end-to-end uitwerken als referentie (voorstel:
   `ahn_relief` op Burgh-Haamstede AOI).
5. Daarna: `bodemopbouw` en `peilbuizen_pastas` parallel.

Geen code voor één van bovenstaande tot dit document is afgetekend.
