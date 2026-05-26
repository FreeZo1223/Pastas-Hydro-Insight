# ArcGIS Online / Ewaarnemingen — Projectregels voor Claude

> **Sessie-changelog:** zie `CHANGELOG.md` (zelfde map) — raadpleeg dit bij de start van een nieuwe sessie voor context over recente wijzigingen.

## Source of Truth: DuckDB

**`Databeheer/00_kern/ewaarnemingen.duckdb` is de enige betrouwbare bron voor analyses en exports.**

> **Migratiegeschiedenis (maart 2026):** De pipeline (`agol_naar_duckdb_v2.py`) schreef vroeger naar `J:\Databeheer\Ewaarnemingen_databeheer` (netwerkschijf). `data/ewaarnemingen.duckdb` is gevuld door die oudere runs. In maart 2026 zijn alle tabellen overgezet naar `Databeheer/00_kern/` en het pipeline-pad is gefixed naar lokaal. `data/ewaarnemingen.duckdb` is sindsdien archief — niet meer de actieve bron.

Lees NOOIT rechtstreeks uit parquet-bestanden voor analyses of exports. De parquets zijn ruwe tussenbestanden die onvolledige datums en geen AGOL-verrijking bevatten. De DuckDB combineert AGOL-live data + parquets + berekende `datum_beste` en is altijd completer.

## Pipeline-flow

```
AGOL REST API  +  parquets (historisch)
          |
          v
agol_naar_duckdb_v2.py        ← ververs periodiek
          |
          v
Databeheer/00_kern/ewaarnemingen.duckdb     ← SOURCE OF TRUTH
          |
          ├── duckdb_naar_geopackage.py
          │     ├── Databeheer/02_geopackage/exports/*_DATUM.gpkg   ← gedateerd archief
          │     ├── Databeheer/02_geopackage/qgis/*.gpkg            ← vaste naam, QGIS-bron (lokaal)
          │     ├── J:/...02_geopackage/qgis/*.gpkg                 ← QGIS-bron collega's
          │     └── J:/...01_parquet/actueel/*.parquet
          │
          ├── duckdb_naar_postgis.py                                 ← PostGIS (multi-user, QField)
          │     └── localhost:5432/ewaarnemingen  schema: ewaarnemingen
          │
          v
convert_to_excel.py           ← eindexport (leest GPKG)
```

**J:-sync:** `run_pipeline.bat` doet robocopy na elke run. Vanuit Claude/MCP wordt de J:-sync geblokkeerd door cryptoblokkerbescherming — handmatig kopiëren na een Claude-run.

## DuckDB: tabellen en sleutelkolommen

Bestand: `C:/GIS_Projecten/ArcGIS_online/Databeheer/00_kern/ewaarnemingen.duckdb`

| Tabel | Records (apr 2026) | Inhoud |
|---|---|---|
| `waarnemingen_vogels` | 82.527 | vogelwaarnemingen, incl. Gierzwaluw |
| `waarnemingen_faunakasten` | 30.553 | faunakast-inventarisaties |
| `waarnemingen_vleermuizen` | 41.031 | vleermuiswaarnemingen (actueel + historie via OBJECTID-range fetching) |
| `waarnemingen_zoogdieren` | 9.633 | zoogdierenwaarnemingen |
| `waarnemingen_flora` | 5.080 | florawaarnemingen |
| `waarnemingen_veldbezoeken` | 4.439 | veldbezoekregistraties |
| `waarnemingen_projectgebieden` | 2.986 | projectgebied-polygonen |
| `waarnemingen_baarn_vogels` | 2.916 | Baarn-specifieke vogeldata |
| `waarnemingen_amfibieen` | 1.730 | amfibieën (AGOL via raw unicode + parquet) |
| `waarnemingen_ongewervelden` | 1.644 | ongewervelden (AGOL + backups gecombineerd) |
| `waarnemingen_veldmateriaal` | 993 | veldmateriaal-registraties |
| `waarnemingen_baarn_vleermuizen` | 582 | Baarn-specifieke vleermuisdata |
| `waarnemingen_reptielen` | 522 | reptielen |
| `waarnemingen_owaarnemingen` | 336 | overige waarnemingen |
| `waarnemingen_vissen` | 239 | viswaarnemingen |
| `waarnemingen_exoten` | 137 | exoten |
| `waarnemingen_vliegroutes` | 76 | vleermuisvliegroutes |
| `_pipeline_log` | — | pipeline run-geschiedenis |

> **Noot record-tellingen:** Bovenstaande cijfers reflecteren de werkelijke staat van de pipeline na alle AGOL-fixes (incl. apr 2026: Vleermuizen_hist nu via OBJECTID-range fetching). Deze cijfers zijn stabiel en groeien dagelijks via `_pipeline_log`. Raadpleeg altijd `_pipeline_log` voor live cijfers, niet deze tabel.

**Sleutelkolommen (lowercase in DuckDB):**

- `soort` — soortnaam (bijv. `'Gierzwaluw'`)
- `datum_beste` — beste beschikbare datum (TIMESTAMP), berekend uit: `datum` > `creation_date` > `ingevoerd_datum`
- `datum_bron` — herkomst van datum (`datum`, `creation_date`, `ingevoerd_datum`, `onbekend`)
- `global_id` — unieke ID voor koppeling terug naar AGOL
- `geometry` — GeoJSON blob, **WGS84 (EPSG:4326)**
- `_bron_type` — `agol_actueel`, `agol_historie`, of `parquet`

Let op: kolomnamen zijn **lowercase** in DuckDB (dus `soort`, niet `Soort`; `datum_beste`, niet `Datum`).

## Geometry in DuckDB — drie formaten

DuckDB bevat geometry in drie formaten afhankelijk van de bronlaag:

| Format | Tabellen | CRS |
|---|---|---|
| GeoJSON string | `exoten`, `flora`, `ongewervelden`, `projectgebieden`, `reptielen`, `veldbezoeken`, `veldmateriaal`, `vissen`, `zoogdieren` | WGS84 (EPSG:4326) |
| GeoJSON als bytes | `faunakasten`, `vleermuizen`, `vogels` | WGS84 (EPSG:4326) |
| WKB bytes (21b=Point, ~50b=lijn/vlak) | `amfibieen`, `baarn_vleermuizen`, `baarn_vogels`, `owaarnemingen`, `vliegroutes` | RD New (EPSG:28992) |

`duckdb_naar_geopackage.py` detecteert het format automatisch en reprojecteert alles naar **EPSG:28992** in de GPKG-export.

Parse-patroon voor eigen scripts:
```python
from shapely import wkb as shapely_wkb
from shapely.geometry import shape
import json

def parse_geom(val):
    if val is None: return None
    if isinstance(val, (bytes, bytearray)):
        try: return shape(json.loads(val.decode("utf-8")))  # GeoJSON bytes
        except: pass
        try: return shapely_wkb.loads(bytes(val))           # WKB bytes
        except: return None
    if isinstance(val, str):
        try: return shape(json.loads(val))                  # GeoJSON string
        except: return None
    return None
```

## Actieve scripts

| Script | Functie | Leest van | Output |
|---|---|---|---|
| `agol_naar_duckdb_v2.py` | AGOL + parquet → DuckDB opfrissen | AGOL + parquet | DuckDB |
| `duckdb_naar_geopackage.py` | DuckDB → GPKG + Parquet (voor QGIS + analyses) | DuckDB | GPKG (qgis/ + exports/), Parquet |
| `duckdb_naar_postgis.py` | DuckDB → PostGIS (multi-user, QField) | DuckDB | PostgreSQL schema `ewaarnemingen` |
| `pipeline_rapport.py` | Rapport: actiepunten, delta-records, stagnatie-detectie | DuckDB + pipeline logs | HTML-rapport lokaal + J:, toast-notificatie |
| `load_ongewervelden.py` | Herstel Ongewervelden uit AGOL + JSON backups | AGOL + backups | DuckDB |
| `extract_gierzwaluwen.py` | Gierzwaluw subset Stichtse Vecht → GPKG | DuckDB | GPKG |
| `convert_to_excel.py` | GPKG → Excel (NDFF-formaat) | GPKG | XLSX |
| `run_pipeline.bat` | Taakplanner entry point: orkestreert alle stappen + retry-logica | — | DuckDB, GPKG, J:-sync, rapport |

## Pipeline vernieuwen

### Automatisch via Windows Taakplanner
`scripts/run_pipeline.bat` — taak: `Ewaarnemingen Pipeline` (service: `postgresql-x64-18`)

**Pipeline-flow:**
1. Wacht max 2 uur op J: beschikbaarheid (retry elke 15 min)
2. AGOL → DuckDB (`agol_naar_duckdb_v2.py`)
3. DuckDB → GPKG + Parquet (`duckdb_naar_geopackage.py`)
4. Sync naar J: (`robocopy /E /MIR /R:3 /W:60`)
5. Genereer HTML-rapport + notificatie (`pipeline_rapport.py`)

**PostGIS nog niet in bat:** `duckdb_naar_postgis.py` moet nog handmatig worden toegevoegd als stap 3b in `run_pipeline.bat`.

### Rapport (`pipeline_rapport.py`)
**Locatie:** `Databeheer/03_logs/rapport_wekelijks.html` (lokaal) + `J:\...\rapport_wekelijks.html`

**Structuur:** Header → Actiepunten-tabel → Lagenlijst → Footer

**Actiepunten** (geen INFO-meldingen meer, alleen actionable):
- HTTP 400-fouten per laag (laagnaam + foutcode uit log geparsed)
- Stagnerende lagen: `delta==0` én recentste datum ouder dan `STAGNATION_DAYS` (standaard: 30 dagen)
- Record-dalingen >5%
- GeoPackage export-fouten
- J:-sync compact als losse regel onder de tabel

**Badge-logica:** GESLAAGD → GEDEELTELIJK (gedeeltelijke fouten of stagnaties) → FOUTEN (volledig gefaald). Nooit FOUTEN als merendeel lagen geslaagd is.

**Uitgesloten van rapport:** `EXCLUDE_FROM_REPORT` bovenaan script — momenteel `baarn_vleermuizen` en `baarn_vogels` (0% datumkwaliteit, geen structurele AGOL-data).

**Notificaties:**
- Windows toast (ingelogde gebruiker)
- Optioneel e-mail (SMTP_HOST + EMAIL_NAAR in `.env` — O365: `smtp.office365.com:587`)

### Handmatig
```bash
cd C:/GIS_Projecten/ArcGIS_online

# Stap 1: AGOL → DuckDB (vereist PYTHONUTF8=1 en volledig python-pad of via PowerShell)
python scripts/agol_naar_duckdb_v2.py

# WAL flushen als duckdb_naar_geopackage.py klaagt over read_only + WAL:
python -c "import duckdb; con = duckdb.connect('Databeheer/00_kern/ewaarnemingen.duckdb'); con.execute('CHECKPOINT'); con.close()"

# Stap 2: DuckDB → GPKG + Parquet
python scripts/duckdb_naar_geopackage.py

# Stap 3b: DuckDB → PostGIS
python scripts/duckdb_naar_postgis.py

# Stap 4: Rapport
python scripts/pipeline_rapport.py --agol-exit 0 --j-beschikbaar 1
```

**Credentials:**
- AGOL: `C:/GIS_Projecten/ArcGIS_online/.env` (`AGOL_USERNAME`, `AGOL_PASSWORD`, optionele SMTP)
- PostgreSQL: `C:/GIS_Projecten/.env` (globaal, geladen door `duckdb_naar_postgis.py`)

**Python-omgeving:** Windows Store Python werkt niet als backgroundproces. Gebruik altijd PowerShell of volledig pad:
```powershell
$env:PYTHONUTF8='1'; python scripts\agol_naar_duckdb_v2.py
```

Pipeline-log raadplegen:
```python
import duckdb
con = duckdb.connect("Databeheer/00_kern/ewaarnemingen.duckdb", read_only=True)
con.execute("SELECT * FROM _pipeline_log ORDER BY run_timestamp DESC LIMIT 5").df()
```

## J:-schijf (collega-toegang)

`J:\Databeheer\Ewaarnemingen_databeheer` is een spiegelkopie van `Databeheer/` op de C:-schijf.

- **DuckDB lezen:** `J:\Databeheer\Ewaarnemingen_databeheer\00_kern\ewaarnemingen.duckdb` (read-only, voor analyses)
- **QGIS lagen:** `J:\Databeheer\Ewaarnemingen_databeheer\02_geopackage\qgis\*.gpkg` — vaste bestandsnamen, worden elke run overschreven
- **Parquet actueel:** `J:\Databeheer\Ewaarnemingen_databeheer\01_parquet\actueel\*.parquet` — geëxporteerd uit DuckDB
- **Schrijven:** nooit — de pipeline schrijft altijd naar C:, daarna sync naar J:
- **Sync:** gebeurt automatisch na elke succesvolle pipeline-run via `run_pipeline.bat` (robocopy /MIR)

## Layer Registry

Als gesproken wordt over "de layer registry" of "laag registry" zijn dit altijd de twee actuele bestanden:

| Bestand | Doel |
|---|---|
| `Databeheer/00_kern/layer_registry.json` | Machine-readable: REST URLs, FeatureServer indices, veldschema's per laag (v2.0, meest recent) |
| `Databeheer/05_context/inventory_master_v2.md` | Human-readable: gedetailleerde veld-analyses, vulgraad percentages, data quality per laag |

Oudere registry-bestanden staan in `archive/oude_registries/` en mogen niet als referentie worden gebruikt.

## PostGIS

PostgreSQL 18 + PostGIS 3.6.2 op `localhost:5432`. Database: `ewaarnemingen`, schema: `ewaarnemingen`.

**Credentials in `C:\GIS_Projecten\.env`** (globaal) — laad dit vóór het project-.env:
```python
load_dotenv(r"C:\GIS_Projecten\.env")
load_dotenv("C:/GIS_Projecten/ArcGIS_online/.env")
```

| Gebruiker | Rol | Gebruik |
|---|---|---|
| `postgres` | superuser | DB-beheer en setup — niet voor scripts |
| `ew_pipeline` | schrijven | import-scripts (`duckdb_naar_postgis.py`) |
| `ew_beheer` | schrijven | GIS-beheerders, QGIS desktop bewerken |
| `ew_collega` | alleen lezen | collega's uitdelen voor QGIS + QField |

**QGIS verbinding:** Host `localhost` (of machine-IP voor collega's), poort `5432`, db `ewaarnemingen`, schema `ewaarnemingen`, user `ew_collega`.

**Tabellen:** 15 soortgroep-tabellen (`waarnemingen_*`), geometrie in EPSG:28992. Baarn-lagen uitgesloten (zie `EXCLUDE` in `duckdb_naar_postgis.py`).

**Vereiste packages:** `geopandas`, `sqlalchemy`, `psycopg2-binary`, `geoalchemy2`, `shapely`

## AGOL-laag specifieks

**Amfibieën** — AGOL-services hebben een `ë` in de naam (`Amfibieën_2024`, `Amfibieën_voor_2024`). Pre-encoded URL `Amfibi%C3%ABn_2024` faalt met "Invalid URL" (AGOL re-decoded de `%`). **Gebruik raw unicode in de URL-string**, dan encodeert `requests` correct: `https://services2.arcgis.com/.../Amfibieën_2024/FeatureServer/4`.

**FeatureServer-indices verifiëren** — bij toevoegen van nieuwe lagen of bij HTTP 400-errors: haal de `FeatureServer?f=json` op en check `layers[].id`. Voorbeeld-fout: in code stond `OWaarnemingen_2024/FeatureServer/0` maar werkelijke index is `11`. `Vliegroutes_vleermuizen_2024` index is `12`, niet `0`.

## Archief

Niet meer actieve scripts en oude data staan in `archive/`:
- `archive/losse_scripts/` — oude eenmalige Python-scripts (jan/mrt 2026)
- `archive/oude_data_jan_mrt_2026/` — oude `.gpkg` en `.duckdb` van jan/mrt
- `archive/oude_exports_2026-mrt/` — geopackage-exports van 30-mrt en 7-apr
- `archive/oude_brondata/` — losse gpkg-brondata van 20 maart
- `archive/oude_snapshots/` — eenmalige parquet-snapshot 21 maart
- `archive/oude_logs/` — oude losse log-bestanden
- `archive/airflow_legacy/` — verlaten Apache Airflow setup
- `archive/docs_oud/` — oudere docs (zit nu in `Databeheer/05_context/`)
- `archive/oude_registries/` — oudere layer_registry versies (NIET als referentie gebruiken)
- `archive/Backups/`, `archive/backup/`, `archive/*.gdb/` — oude geodata-backups

Niet als referentie gebruiken voor nieuwe werkzaamheden.
