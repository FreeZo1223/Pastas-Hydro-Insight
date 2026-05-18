# BeSI Analyse Tool — Instructies voor Claude Code

## Doel
Bouw een herbruikbaar Python-analyseprogramma dat BeSI-kansenkaarten (GeoTIFF/VRT) 
intersect met een onderzoeksgebied (shapefile of GeoPackage) en twee soorten analyses uitvoert:

- **Versie 1**: Soortenrijkdom per cel → prioriteringskaart + soortentabel
- **Versie 2**: Gewogen soortenrijkdom (op beschermingsstatus) → ecologische waardekaart

---

## Projectstructuur (al aanwezig, gebruik exact deze layout)

```
besi_tool/
├── config/
│   ├── settings.py              # Alle paden en parameters (AANPASSEN, niet hardcoden elders)
│   └── species_metadata.csv     # Band → soort → groep → gewicht (voorbeelddata aanwezig)
├── core/
│   ├── loader.py                # Inladen VRT, shapefile, masking, CRS-validatie
│   ├── calculator.py            # Sommen, gewogen rijkdom, cutoff-toepassing
│   └── spatial.py               # Ruimtelijke output, classificatie
├── output/
│   ├── maps.py                  # GeoTIFF + PNG export
│   └── tables.py                # CSV/Excel export soortentabel
├── docs/
│   └── METHODOLOGIE.md          # Beschrijving van de methodologie (aanwezig)
├── main.py                      # Hoofdscript, orkestratie
├── requirements.txt             # Packagelijst (aanwezig)
├── .gitignore                   # Aanwezig
└── CHANGELOG.md                 # Versiebeheer (aanwezig)
```

---

## Wat je moet bouwen

### `main.py`
Het hoofdscript dat via commandline aangeroepen wordt:
```bash
python main.py --gebied "C:/pad/naar/gebied.gpkg" --versie 2 --naam "Projectnaam"
```
- `--gebied`: pad naar shapefile (.shp) of GeoPackage (.gpkg)
- `--versie`: 1 of 2 (welke analyse)
- `--naam`: projectnaam voor output-map (optioneel, anders gebiedsnaam + datum)
- `--groep`: optioneel filter op soortengroep (bv. "Vogels", "Reptielen")

Bij elke run:
1. Maak output-map aan: `OUTPUT_BASE_DIR / {naam}_{datum}/`
2. Sla `run_metadata.json` op (zie specs hieronder)
3. Voer de gekozen analyse uit
4. Sla alle outputs op

### `core/loader.py`
```python
# Functies die je moet implementeren:

def load_study_area(path: str) -> gpd.GeoDataFrame:
    """
    Laad shapefile of GeoPackage.
    - Detecteer automatisch het bestandstype op extensie
    - Valideer dat er geometrieën aanwezig zijn
    - Reprojecteer naar EPSG:28992 als de CRS afwijkt (geen fout, gewoon converteren)
    - Return GeoDataFrame in RD New
    """

def load_vrt(vrt_path: str) -> rasterio.DatasetReader:
    """
    Open de Master VRT.
    - Valideer dat het bestand bestaat
    - Valideer CRS == EPSG:28992
    - Return open dataset (laat sluiten aan aanroeper)
    """

def mask_vrt_to_area(vrt_path: str, study_area: gpd.GeoDataFrame, 
                      band_indices: list = None) -> tuple[np.ndarray, dict]:
    """
    Masker de VRT op het onderzoeksgebied.
    - Gebruik rasterio.mask.mask()
    - Clip eerst op bounding box, dan op exacte polygoon
    - Als band_indices opgegeven: lees alleen die banden (voor groepfilter)
    - Anders: lees alle 235 banden
    - Zet nodata-waarden op 0 vóór teruggeven
    - Return: (array met shape [n_bands, rows, cols], transform_dict)
    - transform_dict bevat: transform, crs, nodata_mask (bool array waar gebied=True)
    """
```

### `core/calculator.py`
```python
def apply_cutoffs(data: np.ndarray, metadata: pd.DataFrame) -> np.ndarray:
    """
    Zet kanswaardes om naar binaire aanwezigheid (0/1) per soort per cel.
    - Gebruik cutoff_value uit metadata per band
    - Return bool array [n_bands, rows, cols]
    - Cellen buiten gebied (nodata) blijven 0
    """

def species_richness(binary_data: np.ndarray) -> np.ndarray:
    """
    Tel het aantal aanwezige soorten per cel.
    - Som over de band-as (axis=0)
    - Return 2D array [rows, cols] met integer tellingen
    """

def weighted_richness(binary_data: np.ndarray, metadata: pd.DataFrame) -> np.ndarray:
    """
    Gewogen soortenrijkdom per cel.
    - Vermenigvuldig elke band met het gewicht uit metadata['weight']
    - Som over band-as
    - Return 2D float array
    - Gewichten zijn gedefinieerd in settings.py (STATUS_WEIGHTS)
    """

def classify_raster(data: np.ndarray, n_classes: int = 5) -> np.ndarray:
    """
    Klassificeer waarden in n gelijke klassen (1 t/m n).
    - Negeer 0-waarden (buiten gebied of geen soorten)
    - Gebruik equal-interval classificatie
    - Return integer array met klassen 0 (buiten) t/m n
    """

def species_table(binary_data: np.ndarray, data_raw: np.ndarray,
                  metadata: pd.DataFrame, nodata_mask: np.ndarray) -> pd.DataFrame:
    """
    Maak een soortentabel voor het onderzoeksgebied.
    Kolommen:
    - dutch_name, scientific_name, species_group, broad_group
    - rl_category, habitat_directive, weight
    - present (bool: scoort ergens boven cutoff binnen gebied)
    - area_ha (oppervlakte cellen boven cutoff, in hectare)
    - mean_score (gemiddelde kansscore binnen aanwezige cellen)
    - max_score (maximale kansscore in gebied)
    Gesorteerd op: weight DESC, area_ha DESC
    """
```

### `core/spatial.py`
```python
def to_geotiff(data: np.ndarray, transform, crs, output_path: str, 
               dtype=None, nodata=0):
    """Schrijf numpy array naar GeoTIFF met rasterio."""

def to_png(data: np.ndarray, output_path: str, colormap: str = 'YlOrRd',
           title: str = '', vmin=None, vmax=None):
    """
    Exporteer als PNG met matplotlib.
    - Gebruik YlOrRd colormap (laag=geel, hoog=rood)
    - Voeg colorbar en titel toe
    - Transparant voor 0-waarden
    """
```

### `output/tables.py`
```python
def export_species_table(df: pd.DataFrame, output_dir: str, naam: str):
    """
    Exporteer soortentabel als:
    - CSV: {naam}_soorten.csv
    - Excel: {naam}_soorten.xlsx met opmaak (header vet, alternerende rijen)
    Filteren op present=True (alleen aanwezige soorten exporteren)
    """

def export_summary_stats(stats: dict, output_dir: str, naam: str):
    """
    Exporteer samenvattende statistieken als tekstbestand {naam}_statistieken.txt
    stats bevat: n_soorten, n_soorten_rl, n_soorten_hrl, 
                 opp_hoog_prio_ha, gem_rijkdom, max_rijkdom
    """
```

---

## run_metadata.json — sla op bij elke run

```json
{
  "run_datum": "2025-01-15T14:32:00",
  "project_naam": "Projectnaam",
  "versie_analyse": 2,
  "gebied_bestand": "C:/pad/naar/gebied.gpkg",
  "gebied_opp_ha": 145.3,
  "vrt_bestand": "C:/GIS_Projecten/Data/BESI_Master.vrt",
  "n_banden_geladen": 235,
  "groep_filter": null,
  "parameters": {
    "n_klassen": 5,
    "cutoff_methode": "metadata"
  },
  "output_map": "C:/GIS_Projecten/Output/Projectnaam_20250115/",
  "python_versie": "3.11.0",
  "package_versies": {
    "rasterio": "1.3.0",
    "geopandas": "0.14.0",
    "numpy": "1.26.0"
  }
}
```

Gebruik `importlib.metadata` voor packageversies en `sys.version` voor Python-versie.

---

## Outputs per versie

### Versie 1 — Soortenrijkdom
| Bestand | Beschrijving |
|---|---|
| `{naam}_soortenrijkdom.tif` | GeoTIFF met aantal soorten per 25m-cel |
| `{naam}_soortenrijkdom.png` | Kaartvisualisatie |
| `{naam}_prioriteit.tif` | Geclassificeerd (5 klassen) |
| `{naam}_prioriteit.png` | Kaartvisualisatie prioriteit |
| `{naam}_soorten.csv` | Soortentabel |
| `{naam}_soorten.xlsx` | Soortentabel met opmaak |
| `{naam}_statistieken.txt` | Samenvattende statistieken |
| `run_metadata.json` | Run-informatie |

### Versie 2 — Gewogen soortenrijkdom (alles van v1 plus)
| Bestand | Beschrijving |
|---|---|
| `{naam}_gewogen_rijkdom.tif` | GeoTIFF met gewogen score per cel |
| `{naam}_gewogen_rijkdom.png` | Kaartvisualisatie |
| `{naam}_ecologische_waarde.tif` | Geclassificeerd (5 klassen) |
| `{naam}_ecologische_waarde.png` | Kaartvisualisatie |

---

## Technische vereisten

- Python 3.10+
- Gebruik **type hints** overal
- Gebruik **logging** (niet print), level INFO voor voortgang, DEBUG voor details
- Elke functie heeft een **docstring**
- **Geen hardcoded paden** — alles via `config/settings.py`
- Foutafhandeling: bij ontbrekend bestand → duidelijke foutmelding, geen stacktrace voor gebruiker
- Lees de VRT in **chunks van maximaal 512x512 pixels** als het gebied groter is dan 1000 ha
- Gebruik `with rasterio.open()` — nooit open laten staan

---

## Belangrijk: wat je NIET hoeft te bouwen
- Geen GUI
- Geen NDFF-koppeling (komt in versie 3)
- Geen connectiviteitsanalyse
- Geen webservice

Houd de code simpel en werkend. Liever minder functies die goed werken dan veel functies die half werken.
