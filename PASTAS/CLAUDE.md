# Project: PASTAS Grondwateranalyse

## Doel
Python-gebaseerde grondwaterstijghoogteanalyse als **vervanging voor Menyanthes/Hydromonitor**.
Peilbuisdata modelleren met de [PASTAS](https://pastas.dev) library, met als eindproduct
een interactief dashboard voor ecohydrologen zonder programmeerkennis.

## Mapstructuur

```
PASTAS/
├── CLAUDE.md                       # Dit bestand
├── README.md                       # Quickstart handleiding
│
├── notebooks/                      # Analyse notebooks (start hier)
│   ├── 01_data_verkenning.ipynb    # Data inladen, visualiseren, seizoenspatroon
│   └── 02_pastas_model.ipynb       # PASTAS model bouwen + GVG/GHG/GLG
│
├── Mantel_Test/                    # Peilbuisdata (DINO + BRO)
│   ├── DINO_Grondwaterstanden/
│   │   ├── B42C0133001.csv         # Filter 001 (ondiep), 1995–2004
│   │   └── B42C0133002.csv         # Filter 002 (dieper), 1995–2004
│   └── BRO_Grondwatermonitoring/
│       └── .../GMW000000069526/
│           ├── GLD000000073324-full.csv
│           └── GLD000000075843-full.csv
│
├── data/
│   └── knmi/                       # Neerslag + verdamping
│       ├── neerslag_knmi_zeeland_simulatie.csv   # Gesimuleerd (KNMI API was offline)
│       └── verdamping_knmi_zeeland_simulatie.csv
│
├── scripts/                        # Hulpscripts
│   ├── maak_pastastore.py          # Bouw PastaStore (Zarr) voor dashboard
│   ├── maak_pastastore_snel.py     # Snellere variant
│   ├── haal_knmi_data.py           # KNMI API ophalen (gebruik als API weer online is)
│   ├── genereer_knmi_dummy.py      # Gesimuleerde KNMI data aanmaken
│   ├── test_volledige_pipeline.py  # End-to-end test
│   ├── test_gxg.py                 # GxG berekening testen
│   ├── patch_gxg.py                # GxG patch (iteratief debuggen)
│   ├── patch_notebooks.py          # Notebooks patchen
│   ├── debug_bro.py                # BRO data debug
│   ├── debug_hydropandas_bro.py    # Hydropandas BRO debug
│   └── alles_fixen_en_notebook_herstarten.py
│
├── dashboard/                      # Streamlit dashboard
│   ├── app.py                      # Hoofdapp (streamlit run app.py)
│   ├── requirements.txt
│   └── data/
│
├── output/                         # Resultaten en figuren
│   ├── model_B42C0133_filter001.pas    # Opgeslagen PASTAS model
│   ├── pastas_model_B42C0133.png
│   ├── seizoenspatroon_B42C0133.png
│   ├── tijdreeks_peilbuis_B42C0133.png
│   └── pastastore/
│       └── B42C0133/               # PastaStore Zarr database
│
└── _pastas_lib/                    # Pastas broncode (GitHub clone: pastas/pastas)
├── pastasdash/                     # PastasDash app (GitHub clone: pastas/pastasdash)
└── pastastore/                     # Pastastore lib (GitHub clone: pastas/pastastore)
```

## Peilbuis info

| Eigenschap | Waarde |
|---|---|
| DINO-ID | B42C0133 |
| BRO-ID | GMW000000069526 |
| Locatie | 3.537°E, 51.578°N (bij Axel, Zeeland) |
| Periode | 1995–2004 (~230 metingen per filter) |
| Filters | 001 (ondiep), 002 (dieper) |
| Referentie | NAP (m) |
| KNMI station | Terneuzen (nr. 742) |

## Architectuur

```
Peilbuis (DINO/BRO) ──────────────────────────────────────────┐
                                                                ↓
Neerslag (KNMI) ──┐                                      Vergelijk
                   ├→ StressModel → Responsfunctie (Gamma) → Simulatie
Verdamping (KNMI)─┘                  (tijdvertraging)
                                           ↓
                                    PastaStore (Zarr)
                                           ↓
                               Streamlit Dashboard (app.py)
```

**Kernconcepten:**
- **NSE** (Nash-Sutcliffe Efficiency): modelkwaliteit (1.0 = perfect)
- **GVG/GHG/GLG**: karakteristieke grondwaterstanden voor ecologie/landbouw
- **PastaStore**: Zarr-database voor opslag van meerdere peilbuizen + modellen
- **Hydropandas**: automatisch ophalen BRO/KNMI data via API

## Omgeving

```powershell
# Notebooks
cd C:\GIS_Projecten\PASTAS
jupyter notebook

# Dashboard
cd C:\GIS_Projecten\PASTAS\dashboard
streamlit run app.py

# PastasDash (aparte conda env)
conda activate pastasdash
pastasdash
# Dan: Load Pastastore → output/pastastore/
```

- **Python**: `pastas` v1.13.2, `pastastore`, `hydropandas`, `streamlit`, `plotly`, `pyproj`
- **Conda env**: `pastasdash` voor PastasDash; standaard env voor notebooks/scripts

## Status & aandachtspunten

- KNMI data is momenteel **gesimuleerd** — vervangen met echte data via `haal_knmi_data.py` zodra KNMI API weer online is
- `_pastas_lib`, `pastasdash`, `pastastore` zijn **gekloonde GitHub repos** (pastas organisatie) — geen eigen code, wel lokale broncode voor debugging/ontwikkeling
- Meerdere patch- en debugscripts aanwezig: duidt op iteratief oplossen van BRO-data en GxG-berekeningsproblemen
- Dashboard (`app.py`) is Streamlit, bedoeld voor ecohydrologen zonder programmeerkennis
- PastaStore output staat in `output/pastastore/B42C0133/`
