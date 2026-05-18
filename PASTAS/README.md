# PASTAS Grondwateranalyse — Aan de slag

Een Python-gebaseerde analyse van peilbuisgegevens, als vervanging voor Menyanthes/Hydromonitor.

---

## Mapstructuur

```
PASTAS/
├── notebooks/                  ← Start hier!
│   ├── 01_data_verkenning.ipynb  ← Stap 1: data inladen & visualiseren
│   └── 02_pastas_model.ipynb     ← Stap 2: PASTAS model bouwen
│
├── Mantel_Test/                ← Peilbuis data (DINO + BRO)
│   ├── DINO_Grondwaterstanden/
│   │   ├── B42C0133001.csv       (filter 001, 1995–2004)
│   │   └── B42C0133002.csv       (filter 002, 1995–2004)
│   └── BRO_Grondwatermonitoring/
│       └── .../GMW000000069526/
│           ├── GLD000000073324-full.csv
│           └── GLD000000075843-full.csv
│
├── data/
│   └── knmi/                   ← Neerslag- en verdampingsdata
│       ├── neerslag_knmi_zeeland_simulatie.csv
│       └── verdamping_knmi_zeeland_simulatie.csv
│
├── scripts/                    ← Python hulpscripts
│   ├── haal_knmi_data.py         (KNMI API ophalen — gebruik als API weer online is)
│   ├── genereer_knmi_dummy.py    (realistische gesimuleerde KNMI data)
│   └── maak_notebooks.py         (notebooks regenereren)
│
└── output/                     ← Resultaten en figuren
```

---

## Snel Starten

### 1. Jupyter starten
```powershell
cd c:\GIS_Projecten\PASTAS
jupyter notebook
```
Ga dan naar de `notebooks/` map en open **01_data_verkenning.ipynb**.

### 2. Volgorde notebooks
| # | Notebook | Wat doe je? |
|---|----------|-------------|
| 1 | `01_data_verkenning.ipynb` | Data inladen, visualiseren, seizoen bekijken |
| 2 | `02_pastas_model.ipynb` | PASTAS model bouwen + kalibreren + GVG/GLG/GHG |

---

## Peilbuis info

| Eigenschap | Waarde |
|-----------|--------|
| DINO-ID | B42C0133 |
| BRO-ID | GMW000000069526 |
| Locatie | 3.537°E, 51.578°N (bij Axel, Zeeland) |
| Periode | 1995–2004 (~230 metingen per filter) |
| Filters | 001 (ondiep) en 002 (dieper) |
| Referentie | NAP (m) |

---

## KNMI Data

De neerslag- en verdampingsdata komt van **KNMI station Terneuzen (nr. 742)**.

- **Momenteel:** Gesimuleerde data (KNMI publieke API tijdelijk offline)
- **Later:** Vervangen met echte data via `python scripts/haal_knmi_data.py`

---

## PASTAS in het kort

```
Peilbuis meting ──────────────────────────────────────────────┐
                                                               ↓
Neerslag (KNMI) ──┐                                     Vergelijk
                   ├→ StressModel → Respons functie → Simulatie
Verdamping (KNMI)─┘    (Gamma)      (tijdvertraging)
```

**Kernconcepten:**
- **NSE** (Nash-Sutcliffe): model kwaliteit (1.0 = perfect)
- **GVG/GHG/GLG**: karakteristieke grondwaterstanden voor ecologie/landbouw
- **Respons functie**: hoe snel/traag de bodem reageert op neerslag

---

## Installatie

```powershell
# PASTAS is al geïnstalleerd (versie 1.13.2)
python -c "import pastas; print(pastas.__version__)"

# Jupyter starten
jupyter notebook
```

---

*Vragen? Zie de [PASTAS documentatie](https://pastas.dev) of de [GitHub repo](https://github.com/pastas/pastas).*
