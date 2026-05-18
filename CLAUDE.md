# GIS-projecten — Claude werkinstructies

## Data-acquisitie — gebruik `geo_stack` als canonieke laag

**Voor alle Nederlandse geo-data**: gebruik de `geo_stack` package
(`C:\GIS_Projecten\geo_stack\`). **Hardcode geen URLs in projectcode.**

Installatie eenmalig per venv:
```bash
pip install -e C:\GIS_Projecten\geo_stack
```

### Voorkeur — smart dispatcher (cloud-native first)
```python
from geo_stack.fetch import fetch_features

# Probeert automatisch cloud-native (DuckDB-streaming, 10–50× sneller),
# valt terug op WFS/REST. Downstream code kent geen URLs.
panden = fetch_features("bag_3d", bbox=(125_000, 460_000, 145_000, 480_000))
sloten = fetch_features("bgt", bbox=..., feature_type="bgt:waterdeel")
```

### Voor specifieke skills (als je het pad expliciet wilt)
```python
from geo_stack.skills import kadaster, ahn, bgt, gee, cloud_native
```

**Beschikbare skills** (zie `geo_stack/data_sources.yaml` voor endpoints):

| Skill | Module | Bron | Cloud-native? |
|-------|--------|------|----------------|
| Kadaster | `skills.kadaster` | PDOK Locatieserver | nee |
| BGT | `skills.bgt` | PDOK BGT WFS | nee (alleen WFS) |
| AHN4 | `skills.ahn` | PDOK AHN4 WCS | nee (raster) |
| 3DBAG / BAG | `skills.cloud_native` | DuckDB streaming | **ja** |
| NDVI | `skills.ndvi_stac` | Sentinel-2 STAC | nee |
| GEE | `skills.gee` | Google Earth Engine | nee (vereist auth) |
| BRO bodem | `skills.bro.bodemkaart` | PDOK BRO WFS | nee |
| BRO peilbuizen | `skills.bro.peilbuizen` | BRO REST | nee |
| KNMI | `skills.knmi` | KNMI Data Platform | nee |
| Discovery | `core.discovery` | capabilities-check | n.v.t. |
| Cache | `core.cache.cached_fetch` | decorator | n.v.t. |
| Normalizer | `core.normalizer` | naar geoptimaliseerde GeoParquet | n.v.t. |

**Waarom**: centrale endpoint-registry, retry-logica, cache-decorator,
provenance-registratie. Voorkomt herhaalde valkuilen (CQL_FILTER op tile-cached
WFS, etc). Volledige documentatie: `C:\GIS_Projecten\geo_stack\README.md`.

**Tests**: 40 unit-tests, draaien zonder netwerk. `cd geo_stack && python -m pytest`.

---

## PDOK — beste aanpak voor kadastrale percelen per lijst

### Voorkeursmethode: PDOK Locatieserver REST API (snelst, meest gericht)
Voor een lijst van specifieke percelen is de **locatieserver de beste aanpak** — sneller dan WFS bulk-download en geen afhankelijkheid van CQL_FILTER.

```python
SEARCH = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
LOOKUP = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/lookup"

# Stap 1: zoek perceel-ID
r = requests.get(SEARCH, params={"q": "LLS00-B-10", "fq": "type:perceel", "rows": "5"})
doc_id = r.json()["response"]["docs"][0]["id"]  # bijv. "pcl-3f43d0c3..."

# Stap 2: haal volledige polygoongeometrie op
r2 = requests.get(LOOKUP, params={"id": doc_id, "fl": "*"})
doc = r2.json()["response"]["docs"][0]
# doc["geometrie_rd"]  → WKT polygoon in EPSG:28992
# doc["geometrie_ll"]  → WKT polygoon in WGS84
# doc["kadastrale_grootte"] → oppervlakte in m²
```

- Zoekformaat: `LLS00-{sectie}-{perceelnummer}` (direct) of `Lelystad {sectie} {nr}`
- Geeft GEEN historische (vervallen) percelen terug
- Voeg **retry-logica** toe: de API kan soms een verbinding resetten bij snelle opeenvolging
- ~0.5s per perceel, ~3 minuten voor 288 percelen

### WMS — NIET geschikt voor vectordata
WMS levert rasterfoto's (PNG/JPEG), geen vectorgeometrie. Kan nooit gebruikt worden om een GeoPackage met percelen te maken.

### PDOK WFS — beperkingen
De volgende PDOK WFS-services zijn tile-cached en **negeren CQL_FILTER** silently (HTTP 200, maar geen filtering):
- `service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0` (BRK Kadastrale Kaart)

**Symptoom:** filter geaccepteerd, resultaat bevat willekeurige features die niet matchen.

**Verificatie vóór gebruik:** stuur filter op onmogelijke waarde (`sectie='BESTAAT_NIET'`). Als er features terugkomen, werkt de filter niet.

**Fallback-aanpak via WFS (als locatieserver niet volstaat):**
1. Download alle features via BBOX (gebruik gemeentegrenzen — zie code hieronder)
2. Filter client-side op `AKRKadastraleGemeenteCodeWaarde` en `statusHistorieCode='G'`
3. WFS-limiet: ~51000 records per BBOX-request (geeft 400 bij hogere startIndex)

### AKR-codes kadastrale gemeenten (Flevoland)
| Gemeente | AKR-code |
|----------|----------|
| Lelystad | `LLS00` |
| Dronten  | `DTN01` |
| Almere   | zoek op via BBOX + centroid |

AKR-code formaat in kadastrale aanduiding: `LLS00B00010` (6-char code + sectie + 5-cijfer perceelnr).

### WFS-limieten
- PDOK Kadastrale Kaart WFS: max ~51000 features per BBOX-request (geeft 400 bij hogere startIndex)
- Splits grote gebieden in sub-bbox's als de gemeente groot is

### Gemeente bbox ophalen
```python
import geopandas as gpd
url = "https://service.pdok.nl/cbs/gebiedsindelingen/2024/wfs/v1_0?service=WFS&version=2.0.0&request=GetFeature&typeName=gebiedsindelingen:gemeente_niet_gegeneraliseerd&outputFormat=application/json&srsName=EPSG:28992"
gdf = gpd.read_file(url)
lelystad = gdf[gdf['statnaam'] == 'Lelystad']
bbox = lelystad.total_bounds  # [xmin, ymin, xmax, ymax]
```
Let op: CQL_FILTER werkt ook hier niet; download alle gemeenten en filter lokaal.

## PostgreSQL / PostGIS

### Verbindingsgegevens
Credentials staan in `C:\GIS_Projecten\.env` — laad dit bestand ALTIJD als eerste bij scripts die PostgreSQL gebruiken:
```python
from dotenv import load_dotenv
load_dotenv(r"C:\GIS_Projecten\.env")   # globaal eerst
load_dotenv("project/.env")             # daarna project-specifiek (overschrijft indien nodig)
```

**Service:** `postgresql-x64-18` (draait als Windows-service op localhost:5432)
**Database:** `ewaarnemingen`
**Schema:** `ewaarnemingen`

### Rollen en gebruikers
| Gebruiker | Rol | Gebruik |
|---|---|---|
| `postgres` | superuser | alleen voor DB-beheer en setup |
| `ew_pipeline` | ew_editor | pipeline-scripts (DuckDB → PostGIS) |
| `ew_beheer` | ew_editor | GIS-beheerders, QGIS desktop bewerken |
| `ew_collega` | ew_readonly | collega's, QField, QGIS alleen lezen |

**Credentials per rol zitten in `C:\GIS_Projecten\.env`** — geef `ew_collega`-credentials aan collega's voor QGIS/QField.

### Pipeline-positie
PostGIS is stap 3b in de Ewaarnemingen-pipeline:
```
AGOL → DuckDB → GeoPackage/Parquet → J:-sync    (bestaand)
             └→ PostGIS (ewaarnemingen schema)    (nieuw, script: duckdb_naar_postgis.py)
```
DuckDB blijft de **bron van waarheid**. PostGIS is een leeslaag voor QGIS en QField.

### Verbinden in QGIS
Laag toevoegen → PostgreSQL → nieuwe verbinding:
- Host: `localhost` (of IP-adres van deze machine voor collega's)
- Database: `ewaarnemingen`
- Schema: `ewaarnemingen`
- Gebruiker: `ew_collega` / wachtwoord: zie `.env`

### Psql snelcommando's
```bash
# Verbinden
psql -U postgres -d ewaarnemingen

# Tabellen in schema
\dt ewaarnemingen.*

# PostGIS versie
SELECT PostGIS_Version();
```

### Vereiste Python-packages voor PostGIS-scripts
```
geopandas, sqlalchemy, psycopg2-binary, shapely
```

## QGIS MCP
Zie memory: standaard template `260407_Layout_a3_liggend.qpt`, skill `/qgis-huisstijl`.

## BRK actualiteit en databronnen

| Bron | Actualiteit | Bevat | Toegang |
|------|-------------|-------|---------|
| PDOK Locatieserver (DKK) | Vorige kalenderdag | Perceelgrenzen, oppervlakte | Gratis, geen auth |
| PDOK WFS/WMS/WMTS | Vorige kalenderdag | Perceelgrenzen (visueel) | Gratis, geen auth |
| PDOK GML download | Vorige kalenderdag | Volledig DKK | Gratis, geen auth |
| BRK Bevragen API | Real-time | Perceelgrenzen + eigenaar/rechten | API-key (Mijn Kadaster) |
| BRK Levering | Dagelijkse mutaties | Volledig BRK incl. historisch | Contract + betaald |

**Conclusie:** Voor geometrie is PDOK (locatieserver) voldoende — bijgewerkt tot gisteren.
Voor eigenaarsinformatie of real-time mutaties: BRK Bevragen via `https://brk.basisregistraties.overheid.nl/api/v2` (403 zonder auth, API-key aanvragen via Mijn Kadaster).

Ontbrekende percelen in PDOK = daadwerkelijk vervallen/gesplitst in BRK, geen actualiteitsprobleem.

## Kadaster — bestandsformaten
- GeoPackage als standaard uitvoerformaat (EPSG:28992)
- CSV met kolommen: `gemeente, sectie, perceelnummer, kadastraal_id`

## Directorystructuur en scope

### Productiecode (actief, lees standaard)
| Directory | Inhoud |
|-----------|--------|
| `geo_stack/` | **Canonieke data-acquisitielaag** — Python package, zie sectie hierboven |
| `ArcGIS_online/` | AGOL sync, DuckDB pipelines, Ewaarnemingen |
| `BeSI/` | BeSI analyse tool |
| `Connectiviteit/` | GBDA/BKN connectiviteitsanalyse, BomenMonitor |
| `PASTAS/` | Grondwateranalyse, Streamlit dashboard |
| `qgis_mcp/` | QGIS MCP server |
| `NSW_toolbox/` | NSW tools |
| `lesa-agent-v2/` | Agentic LESA-pipeline (consumer van geo_stack) |
| `SMP_analyses/` | Habitatgeschiktheid SMP |

### Archief / niet actief — NIET automatisch inlezen
De volgende directories bevatten **oude of inactieve code**. Lees deze alleen als de gebruiker er expliciet naar verwijst.

- `Archief/` — vervallen projecten en scripts
- `StichtseVechtTestAnalyses/` — afgeronde analyserun
- `Test_projecten/` — los testmateriaal
- `*/archive/`, `*/Archive/` — projectspecifieke archieven
- `*/tests/` — unit tests (lees alleen bij debuggen of testschrijven)

### Lange modules
Python-pipelines in dit project kunnen lang zijn (300–1000+ regels). Lees bij grote bestanden **alleen het relevante gedeelte** via offset/limit, tenzij de taak een volledig overzicht vereist. Vraag bij twijfel om de relevante functie of sectie.
