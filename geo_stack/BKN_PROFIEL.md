# BKN-profiel voor geo_stack

> **Doel**: Snelreferentie voor de BKN-pipeline (`BKN_projecten/`) over welke geo_stack-datasets
> gebruikt worden per BKN-conditie, hoe de aanroep werkt, en welke waterschappen welke
> datasets substitueren.
>
> **Machine-leesbare versie**: `BKN_projecten/pipeline/src/reference/condities_bronnen.json`
> **Endpoint-registry**: `geo_stack/data_sources.yaml`
> **Bijgewerkt**: 2026-06-11

---

## Aanroepconventie

```python
from geo_stack.fetch import fetch_features

# Generieke dispatcher — kiest automatisch WFS/REST/ARCGIS_REST op basis van data_sources.yaml
gdf = fetch_features("bgt", bbox=(125_000, 460_000, 145_000, 480_000),
                     feature_type="bgt:begroeidterreindeel")

# Met extra kwargs (typename, layer, etc.)
bodem = fetch_features("bro_bodemkaart", bbox=bbox)
oevers = fetch_features("hhnk_oevers", bbox=bbox, layer_id=3)

# Raster via skill (geen dispatcher-route)
from geo_stack.skills.ahn import fetch_ahn_tile
dsm, dtm = fetch_ahn_tile(bbox=bbox)  # CHM = dsm - dtm
```

---

## Condities → geo_stack datasets

### Pijler A — Abiotiek

| ID | Naam | geo_stack_dataset | Methode | Status |
|----|------|-------------------|---------|--------|
| A1 | Nutriënten bodem | `bro_bodemkaart` + `atlasnk` | Bodemtype → pH/P-proxy; AtlasNK ecologisch_kapitaal_bodem | PROXY |
| A2 | Bodemverontreiniging | `bodemloket` + `atlasnk` | Bekende locaties; toxische_druk_bodem als aanvulling | PROXY |
| A3 | Verdroging (in ontwikkeling) | `bro_grondwater` + `nhi` | GHG/GLG uit BRO; NHI modeluitvoer ~250m | PROXY |
| A4 | Waterkwaliteit P | `hhnk_krw_kwaliteit` (layer_id=3) + `krw_landelijk` | EKR PTOT per waterlichaam | MEET/PROXY |
| A5 | Waterkwaliteit N | `hhnk_krw_kwaliteit` (layer_id=0, 7) + `krw_landelijk` | EKR NTOT + macrofauna | MEET/PROXY |
| A6 | Toxische druk water | `atlasnk` (layer=toxische_druk_water) + `waterkwaliteitsportaal` | Styled WMS = PROXY | PROXY |
| A7 | Lichtvervuiling | `rivm_nachtlicht` + `atlasnk` (layer=lichtemissie_nacht) | VIIRS-data; fallback AtlasNK | PROXY |
| A8 | Geluid (in ontwikkeling) | `atlasnk` (layer=geluid_lden) | Geluid Lden WMS; descriptief | PROXY |

**Waterschaps-substitutie A4/A5:**
- **HHNK** (Noord-Holland Noord): `hhnk_krw_kwaliteit`
- **Andere waterschappen**: `krw_landelijk` (Rijkswaterstaat GeoServer) als fallback
- **Meetwaarden**: `waterkwaliteitsportaal` REST API (handmatig tot dedicated skill)

---

### Pijler B — Inrichting / GBDA

| ID | Naam | geo_stack_dataset | Methode | Status |
|----|------|-------------------|---------|--------|
| B1 | Groen-blauwe dooradering hoeveelheid | `lasreg` + `bgt` | LASREG elementen → oppervlakte/%; BGT als aanvulling | MEET |
| B2 | Lage vegetatie | `ahn` + `bgt` | AHN4 CHM 0-0,5m clip op BGT groen | MEET |
| B3 | Landschapselementen aanwezig | `lasreg` | LASREG groene/blauwe elementen per type | MEET |
| B4 | Poelen | `bgt` + `hhnk_geoserver` | BGT watertype 10-2000 m²; waterschap-legger aanvulling | PROXY |
| B5 | Struiklaag | `ahn` + `bgt` | AHN4 CHM 0,5-5m clip op BGT groen | MEET |
| B6 | Boomkroon | `ahn` + `bgt` + `neo_bomen` | AHN4 CHM >5m; individuele stamposities via NEO API | MEET |
| B7 | Gebouwen als habitat | `bag_wfs` + `ep_online` | Bouwjaar + energielabel → verblijfplaatspotentieel | PROXY |
| B8 | Bodemkwaliteit (in ontwikkeling) | `bro_bodemkaart` + `atlasnk` | Zie A1; descriptief | PROXY |
| B9 | Natuurvriendelijke oevers | `hhnk_oevers` (layer_id=3) + `bgt` | NVO direct uit legger; NDVI-buffer als proxy | MEET/PROXY |
| B10 | Watergangsysteem | `hhnk_geoserver` + `hhnk_oppervlaktewateren` | Legger watergangen + BGT waterdeel | MEET |
| B11 | Soortendiversiteit (in ontwikkeling) | `waarneming_nl` + `gbif` + `atlasnk` | Observaties; AtlasNK soortendiversiteit WMS | PROXY |
| B12 | Oude/monumentale bomen | `monumentale_bomen` + `ahn` | RCE-register; AHN4 CHM >20m proxy | PROXY |
| B13 | GBDA-kwaliteit labeling | `lasreg` + `ahn` | A+–F per 20m segment via CHM breedte/hoogte | MEET |
| B14 | Waterhuishouding (in ontwikkeling) | `hhnk_peilgebieden` + `nhi` | Streefpeilen per peilgebied; NHI GHG/GLG | PROXY |

**Waterschaps-substitutie B9/B10:**
- **HHNK**: `hhnk_oevers` (NVO direct) + `hhnk_oppervlaktewateren` (categorisering)
- **HDSR**: ArcGIS REST `gis.hdsr.nl/arcgis/rest/services` — nog niet in registry
- **Andere**: `bgt` (waterdeel) + `top10nl` als fallback

---

### Pijler C — Beheer & gebruik

| ID | Naam | geo_stack_dataset | Methode | Status |
|----|------|-------------------|---------|--------|
| C1 | Ecologisch beheer | `anlb` + `ndvi` | ANLb contractgebieden; Sentinel-2 NDVI maaifrequentie | PROXY |
| C2 | Beheer natte natuur (in ontwikkeling) | `nnn` + `hhnk_peilgebieden` | NNN-overlap; streefpeilen | PROXY |
| C3 | Soortenarme gebieden (in ontwikkeling) | `ndff` + `waarneming_nl` + `gbif` | Soortenregistraties; kennislacune aanwijzen | GEEN DATA (NDFF-dataverdrag) |
| C4 | Agrarisch natuur- en landschapsbeheer | `anlb` + `brp` | ANLb-contracten; BRP-percelen overlap | MEET |

---

## LGN — ConScape connectiviteitsanalyse

```python
from geo_stack.skills.lgn import clip_lgn
from geo_stack.skills.lgn_reclass import apply_reclass

# Clip LGN2024 op AOI (gebruikt lokaal tif: BKN_projecten/data_groot/LGN2024/LGN2024.tif)
lgn, transform = clip_lgn(bbox=gemeente_bounds, buffer=500, target_resolution=25)

# Omzetten naar ConScape quality + affinity matrices
quality, affinity = apply_reclass(lgn)
```

- **Dataset**: `lgn` in data_sources.yaml
- **Lokaal pad**: `C:\GIS_Projecten\BKN_projecten\data_groot\LGN2024\LGN2024.tif`
- **Resolutie**: 25m, klassen 1-45 (Landelijk Grondgebruik Nederland)
- **Gebruik**: fase 4 connectiviteitsanalyse (ConScape.jl via Julia)

---

## Waterschap-configuratie per gemeente

```yaml
# In config/alkmaar.yaml
waterschap: "HHNK"
```

| Waterschap | geo_stack datasets | Dekking |
|---|---|---|
| HHNK | `hhnk_oevers`, `hhnk_oppervlaktewateren`, `hhnk_krw_kwaliteit`, `hhnk_peilgebieden`, `hhnk_geoserver` | Noord-Holland Noord |
| HDSR | Nog niet in registry — HANDMATIG (`gis.hdsr.nl`) | Utrecht |
| AGV | Nog niet in registry — HANDMATIG | Amstel/Gooi/Vecht |
| Rijnland | Nog niet in registry | Zuid-Holland / Leiden |
| Scheldestromen | Nog niet in registry | Zeeland |
| — | `krw_landelijk` (fallback alle waterschappen) | NL-breed |

**Waterschap toevoegen**: voeg ArcGIS REST of WFS entry toe in `data_sources.yaml` met
prefix `{waterschap_afkorting}_` (bijv. `hdsr_legger`, `hdsr_peilgebieden`).

---

## Handmatige bronnen (GEEN automatische fetcher)

| Dataset | Reden | Actie vereist |
|---------|-------|---------------|
| `ndff` | Dataverdrag Naturalis/Sovon | Afsluiten dataverdrag → export als CSV |
| `lasreg` | Registratie WUR-portaal, download GeoPackage | `lasreg.containers.wur.nl` → cache/lasreg/{gemeente}.gpkg |
| `ep_online` | API-key RVO vereist | Aanvragen via Mijn Kadaster |
| `waterkwaliteitsportaal` | Bespoke REST, deels offline | Verifieer endpoint voor gebruik |
| `neo_bomen` | CC BY-NC-SA, bespoke API | Aanvragen via NEO/SignalEyes |

---

## Dode endpoints (niet gebruiken)

Zie `BKN_projecten/kennis/DODE_ENDPOINTS.md` voor volledig overzicht. Samenvatting:

| Endpoint | Probleem | Alternatief in geo_stack |
|----------|----------|--------------------------|
| AtlasNK GeoServer TCP | TCP-geblokkeerd (2026-06) | `rivm_nachtlicht`, `atlasnk` WMS als fallback |
| WKP REST (oud) | 404 | `waterkwaliteitsportaal` nieuw endpoint |
| PDOK ANLb WFS (oud) | 404 | `anlb` → nieuw PDOK-endpoint |
| BRO Bodemkaart PDOK WFS | Verplaatst naar WUR/BIS | `bro_bodemkaart` → `maps.bodemdata.nl` |

---

## Anti-verzin-doctrine check voor nieuwe gemeenten

Vóór elke rapport-run controleren:

```python
from geo_stack.core.discovery import list_datasets

# Toon alle beschikbare datasets (ook handmatige)
datasets = list_datasets()

# Verifieer bereikbaarheid kritieke endpoints
from geo_stack.core.discovery import check_endpoint
check_endpoint("bro_bodemkaart")   # maps.bodemdata.nl
check_endpoint("hhnk_oevers")      # kaarten.hhnk.nl
check_endpoint("atlasnk")          # geo.atlasnatuurlijkkapitaal.nl
```

Resultaat van elke fetch wordt automatisch geregistreerd in `provenance.json`:
- URL + timestamp + feature-count + bbox
- Gerapporteerde getallen herleidbaar tot ruwe data in cache
- GEEN getal in rapport zonder provenance-entry

---

## Kweekbodem nieuwe waterschappen

Als een gemeente onder een ander waterschap valt:

1. Zoek het ArcGIS REST- of WFS-endpoint van het waterschap (publiek portaal of open data)
2. Voeg toe aan `data_sources.yaml`:
```yaml
  {waterschap}_legger:
    - label: {Waterschap} legger — watergangen (ArcGIS REST)
      endpoint: "https://..."
      service_type: ARCGIS_REST  # of WFS
      source_version: "Legger {jaar}"
      update_cadence: onregelmatig
      default_crs: "EPSG:28992"
      module: "geo_stack.skills.arcgis_rest.fetch_arcgis"
      generic: true
      layers:
        0: "Waterlopen (vastgesteld)"
      note: "B10 — waterschap-specifiek ({gemeente})."
```
3. Update `BKN_projecten/pipeline/src/reference/condities_bronnen.json`:
   - Vervang `hhnk_*` door nieuw dataset-sleutel voor de betreffende gemeente
