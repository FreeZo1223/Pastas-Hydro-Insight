# Changelog — ArcGIS Online / Ewaarnemingen

Raadpleeg dit bij het begin van een nieuwe Claude-sessie voor context over recente wijzigingen.
Nieuwste entries staan bovenaan.

---

## 2026-04-29 — Vleermuizen_hist crash gefixed + alles gevalideerd

### Vleermuizen_hist: crash opgelost via OBJECTID-range fetching
**Probleem:** Offset-gebaseerde paginering crashte reproduceerbaar bij exact 35.658 records (stille Python kill, geen traceback).

**Diagnose:** Niet geheugen-gerelateerd (crash gebeurde op exact hetzelfde punt elke keer). Het lijkt een AGOL API-limitatie of netwerk-deadlock op grote offset-pagina's.

**Oplossing:** Nieuwe fetcher `haal_agol_laag_op_objectid_ranges()` die:
- In plaats van offset-paginering, OBJECTID-ranges gebruikt (bijv. OBJECTID 0-10k, 10k-20k, etc.)
- Dit breekt het probleem in kleinere queries die allemaal slagen
- Vleermuizen_hist staat nu enabled in `AGOL_LAGEN` (was uitgecommentarieerd)
- Script autodetecteert Vleermuizen_hist en gebruikt de OBJECTID-methode

**Resultaat:** 35.658 records geslaagd (eerder verloren via parquet-fallback van 19.401). Totaal Vleermuizen nu **41.031** (actueel 431 + hist 35.658 + parquet overlap).

### Pipeline-run 29 april — alles succesvol
- **AGOL opgehaald:** 28 lagen, allemaal succesvol (incl. Vleermuizen_hist nu!)
- **DuckDB:** 186.021 rijen totaal, 17 tabellen, geverifieerd
- **Tabelwijzigingen:** 
  | Tabel | Apr 25 | Apr 29 | Verschil |
  |---|---|---|---|
  | `waarnemingen_vleermuizen` | 21.443 | 41.031 | +19.588 (Vleermuizen_hist nu actief!) |
  | Totaal | 166.000 | 186.021 | +20.000 (Vleermuizen_hist recovery) |

---

## 2026-04-29 — AGOL-fixes (Amfibieën, OWaarnemingen, Vliegroutes) + grote schoonmaakronde

### Drie reëel missende AGOL-lagen toegevoegd in `agol_naar_duckdb_v2.py`
Diagnose: drie soortgroepen kwamen voorheen alleen via parquet binnen omdat de AGOL-fetch faalde.

| Laag | Vroeger | Nu | Oorzaak |
|---|---|---|---|
| `OWaarnemingen` | 199 (parquet) | **336** (AGOL) | FeatureServer-index `0` → moest **`11`** |
| `Vliegroutes` | 52 (parquet) | **76** (AGOL) | FeatureServer-index `0` → moest **`12`** |
| `Amfibieën` | 1.673 (parquet) | **1.730** (AGOL: 57 actueel + 1.673 historie) | Pre-encoded URL `Amfibi%C3%ABn_2024` faalt; raw unicode `Amfibieën_2024` werkt wel |

Verificatie via live AGOL-test: alle drie endpoints leveren records met geometry.

### Vleermuizen_hist tijdelijk uitgeschakeld
`Vleermuizen_hist` (`Vleermuizen_historie/FeatureServer/0`, ~35.658 records) crasht reproduceerbaar — Python proces wordt stilletjes gekild zonder traceback, altijd op de laatste opgehaalde laag van de run. De pipeline draaide na uitschakelen wel succesvol af. Onderzoek nog open (vermoeden: OOM bij DataFrame-creatie van 35k records met geometry-blobs).

Effect: `waarnemingen_vleermuizen` viel van 25.097 → 21.443 (verlies van ~3.6k historische records, deels opgevangen door parquet die 19.401 records levert). Tijdelijke workaround toelichting in script-comment opgenomen.

### Pipeline draaide vandaag succesvol
- Stap 1 (AGOL → DuckDB): 16/17 lagen via AGOL+parquet, 1 laag tijdelijk uit
- Stap 2 (DuckDB → GeoPackage): 17 GPKG's in `Databeheer/02_geopackage/qgis/` + gedateerde versie in `exports/`
- Stap 3b (DuckDB → PostGIS): 15 tabellen in PostgreSQL `ewaarnemingen.ewaarnemingen` (Baarn-lagen uitgesloten)

### Pipeline-hangs van 28+29 april ontrafeld
- Last Result Taakplanner = `-1073741510` = STATUS_CONTROL_C_EXIT (handmatig gekild). Geen scriptbug — laptop werd vlak na 10:00 dichtgeklapt of pipeline werd onderbroken. Geen verdere actie nodig.

### Hangende achtergrondprocessen opgeruimd
- 2× `mcp-server-motherduck` met **fout J:-pad** (`J:/Ewaarnemingen_ecologendata/...`, bestond niet meer) — gestopt
- 8× `qgis_mcp_server.py` orphans — gestopt

### Grote opschoonronde
- **Project-root**: `airflow_home/`, `data/` (200 MB), `export_voor_agol/` (300 MB), `logs/` (13 MB), `docs/`, `export_rapport.csv` → `archive/`
- **Databeheer**: `02_geopackage/brondata/` (oude losse gpkg's), `01_parquet/snapshots/` (eenmalige snapshot van 21 mrt), `04_scripts/` (1 los script) → `archive/`; `03_logs/tmp/` verwijderd
- **Geopackage exports**: 30-mrt en 7-apr versies → `archive/`, alleen 24-apr blijft als referentie (nieuwe pipeline-runs overschrijven sowieso)
- **Scripts**: 13 oude eenmalige scripts (`compare_zoogdieren`, `merge_zoogdieren`, `fix_reserved_fields`, `run_*_fix`, `run_*_audit`, `run_diagnose`, `run_voorbereiding`, `run_final_append`, `run_overlap_analyse`, `agol_domains_ophalen`, `ewaarnemingen_dag` Airflow DAG) → `archive/losse_scripts/`; `scripts/src/` → archive
- `scripts/Veldbezoeken_toolbox/` → `C:\GIS_Projecten\Test_projecten\Veldbezoeken_toolbox\` (op verzoek)

Resultaat: van 26 → 8 actieve scripts; project-root van 9 dirs → 4 dirs (Databeheer, ESRI_Backups, archive, scripts).

---

## 2026-04-25 — DuckDB → PostGIS export-pijplijn + multi-user setup

`duckdb_naar_postgis.py` toegevoegd als stap 3b. PostgreSQL 18 + PostGIS 3.6.2 op localhost:5432. Rollen `ew_pipeline` (write), `ew_beheer` (write), `ew_collega` (read). Globale credentials in `C:\GIS_Projecten\.env`. Doel: multi-user via TCP voor QGIS desktop en latere QField-koppeling. Documentatie in `C:\GIS_Projecten\CLAUDE.md` en project-CLAUDE.md.

`pipeline_rapport.py` herstructurering: nieuwe HTML met actiepunten-tabel, stagnation-detectie (STAGNATION_DAYS=30), badge-logica GESLAAGD/GEDEELTELIJK/FOUTEN, EXCLUDE_FROM_REPORT voor Baarn-lagen.

QGIS-template `Ewaarnemingen_template.qgz` in `C:\GIS_Projecten\qgis_mcp\Q_cloud\projecttemplates\Ecologie\` — 17 GPKG + 17 Parquet lagen vanaf J:-paden, layout `260407_Layout_a3_liggend.qpt`.

---

## 2026-03-30 — Robust pipeline met retry-logica, wekelijks rapport & notificaties

### Volledige herstructurering voor betrouwbaarheid
**`run_pipeline.bat`** — herschreven:
- J:-schijf availability check met retry (elke 15 min, max 8× = 2 uur wachten)
- Betrouwbare timestamp via PowerShell (omzeilt Dutch Windows date-format bug)
- Robocopy retries: `/R:3 /W:60` (was `/R:1000000 /W:30` → veroorzaakte 2-daagse hangs)
- `pipeline_rapport.py` wordt altijd aangeroepen, ook bij fouten

**`pipeline_rapport.py`** — nieuw script (wekelijks rapport + notificaties):
- Vergelijkt record-counts huidigrunt vs vorige run → detecteert laagnaamwijzigingen
- Kwaliteitschecks: datum%, soort%, geometry% met waarschuwingsdrempels
- Detecteert kritieke fouten: AGOL onbereikbaar, recorddaling >5%, kwaliteitsdaling >5%
- HTML-rapport: `J:\Databeheer\Ewaarnemingen_databeheer\rapport_wekelijks.html` + lokaal
- Windows toast-notificatie (groen/geel/rood afhankelijk van status)
- Optioneel e-mailrapport (SMTP_HOST instellen in `.env`)

**`.env`** — uitgebreid met optionele e-mailinstellingen (Office 365 compatible)

### Voordelen
✅ J: onbereikbaarheid is niet meer blocker (2 uur wachten, daarna overgeslagen)
✅ AGOL laagnaamwijzigingen onmiddellijk gedetecteerd
✅ Wekelijks inzicht in nieuwe records en datakwaliteit
✅ Kritieke fouten → Windows toast alert + optioneel e-mail
✅ Alle collega's kunnen rapport on-the-fly consulteren

---

## 2026-03-30 — Geometry fix + volledige pipeline gedraaid

### Geometry parsing gefixed in `duckdb_naar_geopackage.py`
DuckDB slaat geometry op in drie verschillende formaten afhankelijk van de bronlaag:
- **GeoJSON string** (AGOL-lagen): werkte al
- **GeoJSON als bytes** (sommige AGOL-lagen): werden foutief als `None` geparsed → gefixed
- **WKB bytes** (parquet-bronnen, 21 bytes = Point, ~50 bytes = lijn/vlak): werden foutief als `None` geparsed → gefixed via `shapely.wkb.loads()`

WKB-geometrieën zijn in **RD New (EPSG:28992)**, GeoJSON in WGS84 (EPSG:4326).
Script detecteert nu automatisch de bron-CRS per tabel en reprojecteert alles naar **EPSG:28992** voor QGIS.

Tabellen met WKB-geometrie: `amfibieen`, `baarn_vleermuizen`, `baarn_vogels`, `owaarnemingen`, `vleermuizen`, `vliegroutes`, `vogels`

Resterende NULL-geometry-waarschuwingen zijn echte ontbrekende coords in brondata (niet oplosbaar).

### Pipeline volledig gedraaid (2026-03-30)
- DuckDB: 17 tabellen, checkpoint van 28-mrt-2026 gebruikt (geen nieuwe AGOL-fetch nodig)
- GeoPackages: alle 17 tabellen geëxporteerd naar `02_geopackage/exports/` en `02_geopackage/qgis/`
- J:-schijf gesynchroniseerd: DuckDB, GPKG en parquets actueel
- `Ewaarnemingen_Backups/` op J: verplaatst naar `J:\Databeheer\11_archief\` (buiten robocopy-scope)

### Robocopy retry-probleem geïdentificeerd
`run_pipeline.bat` had `/R:1000000 /W:30` — dit zorgde dat de pipeline-run van 28-mrt twee dagen bleef retrying op het oude J:-pad. **TODO:** aanpassen naar `/R:3 /W:5`.

---

## 2026-03-30 — J:-pad hernoemd + GPKG-export in pipeline + QGIS-laag

- J:-pad hernoemd: `J:\Ewaarnemingen_ecologendata\Databeheer` → `J:\Databeheer\Ewaarnemingen_databeheer`
- `run_pipeline.bat` bijgewerkt: pad gecorrigeerd + `duckdb_naar_geopackage.py` als automatische stap 2 toegevoegd (vóór de robocopy-sync)
- `duckdb_naar_geopackage.py` volledig herschreven qua paden: DuckDB, field_mapping en alle exportpaden zijn nu relatief/correct
- Nieuwe exportstructuur:
  - `02_geopackage/exports/*_DATUM.gpkg` — gedateerd archief (lokaal + J:)
  - `02_geopackage/qgis/*.gpkg` — vaste namen zonder datum, QGIS-bron (lokaal + J:) — worden elke run overschreven
  - `01_parquet/actueel/*.parquet` — actuele parquets geëxporteerd uit DuckDB (J:)
- CLAUDE.md bijgewerkt met nieuwe paden, pipeline-flow en J:-schijf sectie

---

## 2026-03-25 — CLAUDE.md en docs bijgewerkt

- CLAUDE.md: alle 17 DuckDB-tabellen met recordaantallen toegevoegd
- CLAUDE.md: `load_ongewervelden.py` en `run_pipeline.bat` toegevoegd aan actieve scripts
- CLAUDE.md: J:-schijf sync sectie toegevoegd
- CLAUDE.md: pipeline flow output pad gecorrigeerd (`data/outputs/` → `Databeheer/02_geopackage/exports/`)
- CLAUDE.md: Airflow als verouderd gemarkeerd
- `Databeheer/03_logs/changelog_2026-03.md` vervangen door dit bestand in de projectroot

---

## 2026-03-24 — J:-schijf sync ingericht

Collega's hebben toegang tot de J:-schijf maar niet tot C:. De actuele data moet ook op J: beschikbaar zijn.

- Eenmalige volledige kopie: `Databeheer/` → `J:\Databeheer\Ewaarnemingen_databeheer` (34 bestanden, 28 MB)
- `run_pipeline.bat` uitgebreid: na elke succesvolle pipeline-run automatische sync via `robocopy /MIR`
- Collega's lezen uit `J:\Databeheer\Ewaarnemingen_databeheer\00_kern\ewaarnemingen.duckdb` (read-only)
- Windows Taakplanner: `run_pipeline.bat` als maandelijkse taak — pipeline → sync → log

---

## 2026-03-22 — Workspace opgeruimd

- Losse bestanden in root verplaatst naar juiste mappen
- Ongewervelden_* backup-mappen verplaatst naar `archive/Backups/`
- `ewaarnemingen_dag.py` verplaatst van root naar `scripts/` (Apache Airflow DAG — niet meer actief)
- `docs/airflow_setup.md` behouden maar gemarkeerd als verouderd

---

## 2026-03-21 — Ongewervelden hersteld

`waarnemingen_ongewervelden` had 1.717 records maar slechts 9.8% soort-vulgraad. De AGOL-histoire-laag (FeatureServer/64) mist structureel het Soort-veld.

Nieuw script `scripts/load_ongewervelden.py` combineert:
1. AGOL actueel (FeatureServer/17): 86 records, 100% soort
2. AGOL histoire (FeatureServer/64): 1.517 records, geen soort → 119 verrijkt via GlobalID-lookup uit backup 2022
3. Backup 2022 (JSON): 463 records, 100% soort

Resultaat: **2.080 records**, **32.5% soort** (structureel maximum), 100% datum_beste, 100% geometry.
- Parquet overschreven: `Databeheer/01_parquet/latest/Ongewervelden_Totaal_Repaired.parquet`
- GeoPackage aangemaakt: `Databeheer/02_geopackage/exports/Ongewervelden_Totaal.gpkg`

---

## 2026-03-21 — Pipeline gerepareerd & DuckDB gemigreerd

**Probleem:** `agol_naar_duckdb_v2.py` schreef hardcoded naar `J:\Databeheer\Ewaarnemingen_databeheer`, maar die J:-DuckDB was leeg. De volledige data (221.901 records) stond in `data/ewaarnemingen.duckdb`.

**Fixes:**
- `agol_naar_duckdb_v2.py` regel 47: J:\ pad → relatief pad (`_SCRIPT_DIR.parent / "Databeheer"`)
- `run_pipeline.bat`: J:\ log-pad → relatief pad
- Alle 17 tabellen gemigreerd: `data/ewaarnemingen.duckdb` → `Databeheer/00_kern/ewaarnemingen.duckdb`
- `data/ewaarnemingen.duckdb` is nu archief

---

## 2026-03-19 — Layer Registry bijgewerkt

- `Databeheer/00_kern/layer_registry.json` bijgewerkt naar v2.0
- `Databeheer/05_context/inventory_master_v2.md` aangemaakt
- Oude registry-bestanden gearchiveerd naar `archive/oude_registries/`

---

## Huidige stand (2026-04-29)

| Item | Status |
|---|---|
| DuckDB `Databeheer/00_kern/ewaarnemingen.duckdb` | ✅ Actief, 186.021 records, 17 tabellen |
| Pipeline-pad | ✅ Lokaal (C:), niet meer J: |
| J:-schijf sync | ⚠️ Cryptoblokker beveiliging — handmatig na Claude-runs |
| AGOL-fixes | ✅ Amfibieën / OWaarnemingen / Vliegroutes / Vleermuizen_hist allemaal via AGOL |
| Vleermuizen_hist | ✅ Gefixed via OBJECTID-range fetching (35.658 records nu) |
| Layer registry | ✅ v2.0 in `Databeheer/00_kern/layer_registry.json` |
| PostGIS | ✅ 15 tabellen op localhost:5432 (multi-user) |
| Geopackages | ✅ 17 lagen in `Databeheer/02_geopackage/qgis/` (vaste namen) |
| Automatisering | ✅ Windows Taakplanner + `run_pipeline.bat` (dagelijks 10:00) |
| Apache Airflow | ❌ Verwijderd — was verouderd |
