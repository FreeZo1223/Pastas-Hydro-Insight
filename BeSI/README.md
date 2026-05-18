# BeSI Analyse Tool

**Beschermde Soorten Indicator** — een bureaustudie-instrument dat op basis van landelijke kansenkaarten berekent welke beschermde soorten in een onderzoeksgebied verwacht kunnen worden, en waar de ecologisch meest waardevolle zones liggen.

---

## Wat doet de tool?

BeSI beantwoordt twee vragen:

1. **Welke beschermde soorten zijn te verwachten?** — per soort wordt de kans op voorkomen vergeleken met een soortspecifieke drempelwaarde (cutoff). Soorten boven die drempel tellen mee.
2. **Waar in het gebied is de ecologische waarde het hoogst?** — door soortenrijkdom of gewogen soortenrijkdom ruimtelijk te aggregeren per 25×25 m cel ontstaan prioriteringskaarten.

De tool is een **bureaustudie-instrument**, geen vervanging van veldonderzoek. Hoge kansscores betekenen niet dat een soort zeker aanwezig is.

---

## Databron

De analyses zijn gebaseerd op de **BeSI Kansenkaarten 2025** (Sierdsema et al. 2026, Sovon-rapport 2025/78), ontwikkeld door Sovon Vogelonderzoek Nederland in opdracht van BIJ12.

| Eigenschap | Waarde |
|------------|--------|
| Resolutie | 25 × 25 meter |
| Projectie | EPSG:28992 (RD New) |
| Soorten | 235 beschermde soorten |
| Soortengroepen | Vogels, zoogdieren, reptielen, amfibieën, vissen, insecten, vaatplanten, weekdieren |
| Modelmethode | Random Forest regressie + ruimtelijke interpolatie van residuen |
| Maskers | Areaalmasker (bekende verspreiding) + habitatmasker |

De kansenkaarten worden als Cloud Optimized GeoTIFFs (COG) per soort opgeslagen en via een VRT-bestand (`BESI_Master.vrt`) als 235-bands raster beschikbaar gesteld. De waarden zijn gecodeerd als bytes (0–255), waarbij 255 overeenkomt met een kans van 1,0.

---

## Installatie

### Vereisten

- Python 3.10+
- De COG-bestanden van de BeSI Kansenkaarten (235 GeoTIFFs) in de geconfigureerde map
- Het `BESI_Master.vrt` bestand in de BeSI-projectmap

### Python-packages

```bash
pip install -r requirements.txt
```

Benodigde packages: `rasterio`, `geopandas`, `numpy`, `pandas`, `matplotlib`, `shapely`, `fiona`, `pyproj`, `openpyxl`

### Configuratie

Pas `config/settings.py` aan voor de lokale installatie:

```python
VRT_PATH = Path(r"C:\GIS_Projecten\BeSI\BESI_Master.vrt")      # pad naar VRT
OUTPUT_BASE_DIR = Path(r"C:\GIS_Projecten\Output")              # uitvoermap
SPECIES_METADATA_PATH = Path(r"config/species_metadata.csv")    # meegeleverd
```

---

## Gebruik

```bash
python main.py --gebied <invoerbestand> --versie <1 of 2> [--naam <projectnaam>] [--groep <soortengroep>]
```

### Argumenten

| Argument | Verplicht | Beschrijving |
|----------|-----------|--------------|
| `--gebied` | ja | Studiegebied als shapefile (`.shp`) of GeoPackage (`.gpkg`), elke projectie |
| `--versie` | ja | `1` = soortenrijkdom, `2` = gewogen soortenrijkdom (inclusief alle versie-1-uitvoer) |
| `--naam` | nee | Projectnaam voor uitvoermapnaam en bestandsnamen (standaard: bestandsnaam invoer) |
| `--groep` | nee | Filter op soortengroep, bijv. `Vogels`, `Zoogdieren`, `Reptielen` |

### Voorbeelden

```bash
# Volledige analyse versie 2
python main.py --gebied invoer/Woldberg.gpkg --versie 2 --naam Woldberg

# Alleen vogels, versie 1
python main.py --gebied invoer/gebied.shp --versie 1 --naam MijnGebied --groep Vogels
```

---

## Werkwijze

De tool voert de volgende stappen in volgorde uit:

```
1. Studiegebied laden            Shapefile/GeoPackage → GeoDataFrame (herprojected naar EPSG:28992)
2. VRT openen                    235-bands raster met kansscore per soort
3. Koppeling metadata            Soortsnaam uit bestandsnaam COG → rij in species_metadata.csv
4. Ruimtelijk maskeren           Raster uitknippen op studiegebied, bytes normaliseren naar 0–1
5. Cutoffs toepassen             Kans ≥ cutoff(soort) → True/False per cel per soort
6. Soortenrijkdom berekenen      Som van aanwezige soorten per cel (integer raster)
7. Prioriteit classificeren      Gelijke-interval 5 klassen op niet-nulcellen
8. Soortentabel opstellen        Aanwezigheid, oppervlakte, gemiddelde score, beschermingsstatus
9. [Versie 2] Gewogen rijkdom    Som van gewicht(soort) × aanwezig(soort) per cel (float raster)
10. Resultaten exporteren         GeoTIFF + PNG + CSV + Excel + statistieken + run_metadata.json
```

---

## Methodologie

### Cutoff — soortspecifieke drempelwaarde

De cutoffwaarde per soort is afgeleid uit bijlage 3 van het Sovon-rapport, bepaald via de True Skill Statistic (TSS) met een correctie voor BeSI-gebruik: type I fouten (soort aanwezig, model zegt afwezig) worden zwaarder gewogen dan type II fouten. Dit resulteert in een conservatieve drempel die de kans op het missen van aanwezige soorten minimaliseert. De standaard fallback-cutoff voor soorten zonder metadatarij is 0,30.

### Versie 1 — Soortenrijkdom

```
soortenrijkdom(cel) = Σ [ kansscore(soort, cel) ≥ cutoff(soort) ]
```

Produceert een integer raster (aantal verwachte soorten per cel). De prioriteringskaart gebruikt gelijke-interval classificatie in 5 klassen over niet-nulcellen; klasse 5 is hoogste prioriteit.

### Versie 2 — Gewogen soortenrijkdom

```
gewogen_rijkdom(cel) = Σ [ aanwezig(soort, cel) × gewicht(soort) ]
```

Het gewicht per soort combineert de Rode Lijst-categorie en de status op de Habitatrichtlijn:

| Factor | Waarde |
|--------|--------|
| Rode Lijst CR | 5 |
| Rode Lijst EN | 4 |
| Rode Lijst VU | 3 |
| Rode Lijst NT | 2 |
| Rode Lijst LC / DD / NE | 1 |
| Habitatrichtlijn Bijlage IV | +3 |
| Habitatrichtlijn Bijlage II | +2 |
| Habitatrichtlijn Bijlage II + IV | +4 |
| Vogelrichtlijn Bijlage I | +2 |
| Habitatrichtlijn Bijlage V | +1 |

Voorbeeld: Geelbuikvuurpad (CR + HR Bijlage II+IV) krijgt gewicht 9; een gewone soort als Bruine kikker (LC, geen richtlijn) krijgt gewicht 1.

De gewogen kaart benadrukt zones waar zeldzame en zwaar beschermde soorten samenkomen, ook als de absolute soortenrijkdom daar niet het hoogst is.

---

## Uitvoer

Alle resultaten worden opgeslagen in `<OUTPUT_BASE_DIR>/<naam>_<datum>/`:

| Bestand | Beschrijving | Versie |
|---------|--------------|--------|
| `{naam}_soortenrijkdom.tif/.png` | Integer raster: aantal verwachte soorten per cel | 1 + 2 |
| `{naam}_prioriteit.tif/.png` | 5-klassen prioriteringskaart (gelijke-interval) | 1 + 2 |
| `{naam}_soorten.csv` | Soortentabel: aanwezige soorten met scores en beschermingsstatus | 1 + 2 |
| `{naam}_soorten.xlsx` | Opgemaakte Excel-versie van de soortentabel | 1 + 2 |
| `{naam}_statistieken.txt` | Tekstsamenvatting: aantallen, oppervlakten, hoge-prioriteitsdrempel | 1 + 2 |
| `{naam}_gewogen_rijkdom.tif/.png` | Float raster: gewogen ecologische score per cel | 2 |
| `{naam}_ecologische_waarde.tif/.png` | 5-klassen ecologische waardekaart | 2 |
| `run_metadata.json` | Herkomstregistratie: invoerpaden, parameters, packageversies | 1 + 2 |
| `run.log` | Tijdgestempeld proceslogboek | 1 + 2 |

---

## Projectstructuur

```
BeSI/
├── main.py                     # Enige entry point, orkestreert de volledige pipeline
├── requirements.txt
├── BESI_Master.vrt             # VRT die alle 235 COG-bestanden samenvoegt (niet in git)
├── config/
│   ├── settings.py             # Alle paden en instelbare parameters — pas dit aan per installatie
│   └── species_metadata.csv   # 235 soorten: groep, Rode Lijst, HR-status, cutoff, gewicht
├── core/
│   ├── loader.py               # Studiegebied laden, VRT openen, ruimtelijk maskeren
│   ├── calculator.py           # Alle numerieke logica: cutoffs, rijkdom, gewogen rijkdom, classificatie
│   └── spatial.py              # GeoTIFF- en PNG-schrijvers (rasterio / matplotlib)
├── output/
│   ├── maps.py                 # Exporteert kaartproducten met juiste kleuren en bestandsnamen
│   └── tables.py               # Exporteert CSV, Excel en statistiekbestand
└── docs/
    └── METHODOLOGIE.md         # Uitgebreide methodologische documentatie
```

---

## Beperkingen

1. **Modelonzekerheid** — de kansenkaarten zijn modellen, geen garanties. Hoge kansscore ≠ soort is zeker aanwezig.
2. **Temporele dekking** — modellen zijn gebaseerd op waarnemingen uit 2003–2024 (afhankelijk van soortengroep). Recente populatieveranderingen zijn mogelijk niet weerspiegeld.
3. **Areaalmasker** — buiten het bekende verspreidingsareaal geeft het model altijd 0, ook als het habitat geschikt lijkt.
4. **Geen connectiviteitsanalyse** — de tool analyseert de inhoud van het onderzoeksgebied, niet de ecologische samenhang met de omgeving.
5. **Zwartkop ontbreekt** — het bronbestand was corrupt bij verwerking. Alle overige 235 soorten zijn beschikbaar.

---

## Referentie

Sierdsema, H., Kampichler, C. & Gallego Zamorano, J. 2026. *Toelichting kansenkaarten beschermde soorten 2025.* Sovon-rapport 2025/78. Sovon Vogelonderzoek Nederland, Nijmegen.
