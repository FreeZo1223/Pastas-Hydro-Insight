"""
maak_notebooks.py
=================
Genereert de twee Jupyter notebooks voor het PASTAS project.
Uitvoer:
  notebooks/01_data_verkenning.ipynb
  notebooks/02_pastas_model.ipynb

Gebruik:
  python scripts/maak_notebooks.py
"""

import json
from pathlib import Path

NOTEBOOKS_DIR = Path(__file__).parent.parent / "notebooks"
NOTEBOOKS_DIR.mkdir(exist_ok=True)


def maak_notebook(naam: str, cellen: list) -> None:
    """Schrijft een Jupyter notebook naar schijf."""
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.13.0"
            }
        },
        "cells": cellen
    }
    pad = NOTEBOOKS_DIR / naam
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(notebook, f, ensure_ascii=False, indent=1)
    print(f"  Geschreven: {pad}")


def markdown_cel(tekst: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": tekst.strip()
    }


def code_cel(code: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": code.strip()
    }


# ══════════════════════════════════════════════════════════════════
#  NOTEBOOK 1: Data Verkenning
# ══════════════════════════════════════════════════════════════════
nb1_cellen = [

    markdown_cel("""# 📊 Notebook 1: Data Verkenning Peilbuis B42C0133

**Doel:** De DINO- en BRO-peilbuisdata inladen, bekijken en visualiseren.

---

## Locatie
- **Peilbuis:** B42C0133 (DINO) / GMW000000069526 (BRO)
- **Coördinaten:** 3.537°E, 51.578°N (bij Axel/Terneuzen, Zeeland)
- **Filters:** 001 en 002 (DINO), buisnummers 1 en 2 (BRO)
- **Periode:** 1995–2004 (ca. 230 metingen per filter, 2x per maand)

---

> 💡 **Tip voor beginners:** Voer elke cel uit met **Shift + Enter**. De uitvoer verschijnt direct onder de cel.
"""),

    markdown_cel("## Stap 1: Importeer benodigde bibliotheken"),

    code_cel("""import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# Stel in dat figuren direct in de notebook verschijnen
%matplotlib inline
plt.rcParams['figure.figsize'] = (14, 5)
plt.rcParams['font.size'] = 11

print("Bibliotheken geladen!")
print(f"  pandas versie: {pd.__version__}")
"""),

    markdown_cel("""## Stap 2: DINO data inladen

De DINO CSV heeft een specieke opzet:
- **Regel 1–12:** Metadata (locatie, filter info, referentie)
- **Regel 13+:** Meetdata (datum, stand t.o.v. MP/MV/NAP)

We gebruiken de kolom **'Stand (cm t.o.v NAP)'** — dat is de grondwaterstand 
ten opzichte van Normaal Amsterdams Peil, omgezet naar meters.
"""),

    code_cel("""# Pad naar de data mappen (relatief aan de notebooks/ map)
DATA_DIR = Path("..") / "Mantel_Test"
DINO_DIR = DATA_DIR / "DINO_Grondwaterstanden"
BRO_DIR  = DATA_DIR / "BRO_Grondwatermonitoring" / "BRO_Grondwatermonitoringput" / "GMW000000069526"

def lees_dino_csv(pad: Path) -> pd.Series:
    \"\"\"
    Leest een DINO grondwaterstandsbestand in.
    
    Stappen:
    1. Sla de eerste 12 metaregels over
    2. Lees de meetdata
    3. Converteer datum en NAP-waarden (cm -> m)
    
    Geeft een pandas Series terug met een DatetimeIndex.
    \"\"\"
    # Sla metadata-header over (12 regels)
    df = pd.read_csv(
        pad,
        skiprows=12,       # eerste 12 regels zijn metadata
        sep=",",
        quotechar='\"',
        encoding="utf-8"
    )
    
    # Kolomnamen opschonen (verwijder aanhalingstekens en spaties)
    df.columns = df.columns.str.strip().str.strip('\"')
    
    # Selecteer alleen de datum en NAP-kolom
    datum_kolom = "Peildatum"
    nap_kolom   = "Stand (cm t.o.v NAP)"
    
    # Zet datum om naar datetime
    df[datum_kolom] = pd.to_datetime(df[datum_kolom], format="%d-%m-%Y")
    df = df.set_index(datum_kolom)
    df.index.name = "Datum"
    
    # Converteer cm naar m (NAP)
    gws = df[nap_kolom] / 100.0   # cm → m
    gws.name = pad.stem            # naam = bestandsnaam zonder extensie
    
    # Verwijder eventuele ontbrekende waarden
    gws = gws.dropna()
    
    return gws


# Lees filter 001 en 002
gws_001 = lees_dino_csv(DINO_DIR / "B42C0133001.csv")
gws_002 = lees_dino_csv(DINO_DIR / "B42C0133002.csv")

print(f"Filter 001 geladen: {len(gws_001)} metingen")
print(f"  Periode: {gws_001.index.min().date()} - {gws_001.index.max().date()}")
print(f"  Min/Max: {gws_001.min():.2f} / {gws_001.max():.2f} m NAP")
print()
print(f"Filter 002 geladen: {len(gws_002)} metingen")
print(f"  Periode: {gws_002.index.min().date()} - {gws_002.index.max().date()}")
print(f"  Min/Max: {gws_002.min():.2f} / {gws_002.max():.2f} m NAP")
"""),

    markdown_cel("""## Stap 3: BRO data inladen

De BRO GLD (Grondwaterstandonderzoek Landelijke Database) heeft een andere opmaak:
- Waterstand staat in **meters** (niet cm)
- Datum heeft een **tijdzone suffix** (bijv. `+01:00`)
"""),

    code_cel("""def lees_bro_csv(pad: Path) -> pd.Series:
    \"\"\"
    Leest een BRO Grondwaterstandsbestand in.
    
    Geeft een pandas Series terug (waterstand in m NAP).
    \"\"\"
    # Sla de 9 metaregels over — rij 10 (index 9) is de kolomnamenregel
    df = pd.read_csv(
        pad,
        skiprows=9,        # regels 1-9 zijn BRO metadata, rij 10 = header
        sep=",",
        quotechar='\"',
        encoding="utf-8"
    )
    df.columns = df.columns.str.strip().str.strip('\"')
    
    # Verwijder lege rijen
    df = df.dropna(subset=["waterstand"])
    
    # Datum met tijdzone omzetten (bijv. "1995-01-13T12:00:00+01:00")
    df["tijdstip meting"] = pd.to_datetime(
        df["tijdstip meting"], 
        utc=True                    # interpreteer met tijdzone
    ).dt.tz_localize(None)          # verwijder tijdzone voor eenvoud
    df = df.set_index("tijdstip meting")
    df.index.name = "Datum"
    df.index = df.index.normalize() # houd alleen de datum, niet het tijdstip
    
    # Waterstand is al in meters
    gws = pd.to_numeric(df["waterstand"], errors="coerce").dropna()
    gws.name = pad.stem
    
    return gws


# Lees de twee BRO bestanden
bro_73324 = lees_bro_csv(BRO_DIR / "GLD000000073324-full.csv")
bro_75843 = lees_bro_csv(BRO_DIR / "GLD000000075843-full.csv")

print(f"BRO GLD000000073324 geladen: {len(bro_73324)} metingen")
print(f"  Periode: {bro_73324.index.min().date()} → {bro_73324.index.max().date()}")
print(f"  Min/Max: {bro_73324.min():.2f} / {bro_73324.max():.2f} m NAP")
print()
print(f"BRO GLD000000075843 geladen: {len(bro_75843)} metingen")
print(f"  Periode: {bro_75843.index.min().date()} → {bro_75843.index.max().date()}")
"""),

    markdown_cel("## Stap 4: DINO vs BRO vergelijken"),

    code_cel("""# Combineer DINO en BRO in één DataFrame voor vergelijking
vergelijking = pd.DataFrame({
    "DINO filter 001 (m NAP)": gws_001,
    "DINO filter 002 (m NAP)": gws_002,
    "BRO filter 2 (m NAP)":    bro_73324,
})

print("Eerste paar rijen:")
print(vergelijking.head(10).to_string())
print()
print("Beschrijvende statistieken:")
print(vergelijking.describe().round(3).to_string())
"""),

    markdown_cel("## Stap 5: Tijdreeks visualiseren"),

    code_cel("""fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

# Bovenste grafiek: filter 001 DINO vs BRO
ax1.plot(gws_001.index, gws_001.values, 
         color="#1565C0", linewidth=1.5, marker=".", markersize=4,
         label="DINO filter 001")
ax1.plot(bro_73324.index, bro_73324.values, 
         color="#E53935", linewidth=1.5, marker=".", markersize=4, alpha=0.7,
         label="BRO filter 2")
ax1.set_ylabel("Grondwaterstand [m NAP]")
ax1.set_title("Peilbuis B42C0133 — Grondwaterstanden 1995–2004")
ax1.legend()
ax1.grid(True, alpha=0.3)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.2f} m"))

# Onderste grafiek: filter 002
ax2.plot(gws_002.index, gws_002.values, 
         color="#2E7D32", linewidth=1.5, marker=".", markersize=4,
         label="DINO filter 002 (dieper)")
ax2.set_ylabel("Grondwaterstand [m NAP]")
ax2.set_xlabel("Datum")
ax2.legend()
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax2.xaxis.set_major_locator(mdates.YearLocator())

plt.tight_layout()

# Opslaan
output_pad = Path("..") / "output" / "tijdreeks_peilbuis_B42C0133.png"
output_pad.parent.mkdir(exist_ok=True)
plt.savefig(output_pad, dpi=150, bbox_inches="tight")
print(f"Figuur opgeslagen: {output_pad}")
plt.show()
"""),

    markdown_cel("""## Stap 6: Seizoenspatroon analyseren

Grondwater reageert op neerslag (stijgt) en verdamping (daalt).
We verwachten hogere standen in winter/voorjaar en lagere in zomer/najaar.
"""),

    code_cel("""# Maandelijkse gemiddelden
maandgems = gws_001.groupby(gws_001.index.month).mean()
maanden_namen = ["Jan","Feb","Mrt","Apr","Mei","Jun","Jul","Aug","Sep","Okt","Nov","Dec"]

fig, ax = plt.subplots(figsize=(10, 4))
bars = ax.bar(
    range(1, 13), 
    maandgems.values, 
    color=["#1565C0" if v >= maandgems.mean() else "#F57C00" for v in maandgems.values],
    alpha=0.85,
    edgecolor="white"
)
ax.set_xticks(range(1, 13))
ax.set_xticklabels(maanden_namen)
ax.set_ylabel("Gemiddelde grondwaterstand [m NAP]")
ax.set_title("Seizoenspatroon — Maandgemiddelden DINO filter 001 (1995–2004)")
ax.grid(axis="y", alpha=0.3)

# Referentielijn op gemiddelde
ax.axhline(maandgems.mean(), color="red", linestyle="--", linewidth=1.5, 
           label=f"Gemiddelde: {maandgems.mean():.2f} m")
ax.legend()

plt.tight_layout()
plt.savefig(Path("..") / "output" / "seizoenspatroon_B42C0133.png", dpi=150, bbox_inches="tight")
plt.show()

print("✓ Notebook 1 afgerond!")
print("  Ga verder naar Notebook 02_pastas_model.ipynb voor de tijdreeksanalyse.")
"""),

]

# ══════════════════════════════════════════════════════════════════
#  NOTEBOOK 2: PASTAS Model
# ══════════════════════════════════════════════════════════════════
nb2_cellen = [

    markdown_cel("""# 🔬 Notebook 2: PASTAS Tijdreeksmodel

**Doel:** Een PASTAS model bouwen dat de grondwaterstand verklaart 
vanuit neerslag en verdamping.

--- 

## Hoe werkt PASTAS?

```
Neerslag (P)  ─┐
                ├─→ Stressmodel ─→ Grondwater respons ─→ Gesimuleerde GWS
Verdamping (E)─┘                                          ↓ vergelijk ↓
                                                      Gemeten GWS (peilbuis)
```

**Terminologie:**
| Term | Uitleg |
|------|--------|
| **Stress** | Invoer: neerslag-verdamping (= neerslagoverschot) |
| **Respons functie** | Hoe de bodem reageert op neerslag (bijv. traag/snel) |
| **Model** | Combinatie van stresses + respons → gesimuleerde waterstand |
| **Kalibratie** | Het model aanpassen zodat simulatie ≈ meting |
| **GVG/GLG/GHG** | Gemiddeld Voorjaarsgrondwater / Laagste / Hoogste |

> 💡 PASTAS is vergelijkbaar met wat Menyanthes doet, maar dan in Python — 
> veel meer flexibel en volledig open source.
"""),

    markdown_cel("## Stap 1: Bibliotheken importeren"),

    code_cel("""import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import pastas as ps
from pathlib import Path

%matplotlib inline
plt.rcParams['figure.figsize'] = (14, 5)

print(f"PASTAS versie: {ps.__version__}")
print("Bibliotheken geladen!")
"""),

    markdown_cel("## Stap 2: Peilbuisdata inladen"),

    code_cel("""DATA_DIR = Path("..") / "Mantel_Test"
DINO_DIR = DATA_DIR / "DINO_Grondwaterstanden"


def lees_dino_csv(pad: Path) -> pd.Series:
    \"\"\"Laadt een DINO grondwaterstands-CSV in als pandas Series (m NAP).\"\"\"
    df = pd.read_csv(pad, skiprows=12, sep=",", quotechar='\"', encoding="utf-8")
    df.columns = df.columns.str.strip().str.strip('\"')
    df["Peildatum"] = pd.to_datetime(df["Peildatum"], format="%d-%m-%Y")
    df = df.set_index("Peildatum")
    df.index.name = "Datum"
    gws = df["Stand (cm t.o.v NAP)"].dropna() / 100.0  # cm → m
    gws.name = pad.stem
    return gws


# We gebruiken filter 001 voor het model
gws = lees_dino_csv(DINO_DIR / "B42C0133001.csv")

print(f"Peilbuisdata geladen: {len(gws)} metingen")
print(f"Periode: {gws.index.min().date()} → {gws.index.max().date()}")
print(f"Gemiddelde stand: {gws.mean():.2f} m NAP")
"""),

    markdown_cel("## Stap 3: Neerslags- en verdampingsdata inladen"),

    code_cel("""KNMI_DIR = Path("..") / "data" / "knmi"

# Probeer echte KNMI data, anders gebruiken we de gesimuleerde data
neerslag_bestanden = list(KNMI_DIR.glob("neerslag_*.csv"))
verdamping_bestanden = list(KNMI_DIR.glob("verdamping_*.csv"))

if not neerslag_bestanden:
    raise FileNotFoundError(
        "Geen neerslag CSV gevonden in data/knmi/. "
        "Voer eerst scripts/genereer_knmi_dummy.py uit."
    )

neerslag_pad = neerslag_bestanden[0]
verdamping_pad = verdamping_bestanden[0]

print(f"Neerslag bestand: {neerslag_pad.name}")
print(f"Verdamping bestand: {verdamping_pad.name}")

# Inladen
neerslag = pd.read_csv(
    neerslag_pad, index_col="Datum", parse_dates=True
).iloc[:, 0]   # eerste kolom
neerslag.name = "Neerslag"

verdamping = pd.read_csv(
    verdamping_pad, index_col="Datum", parse_dates=True
).iloc[:, 0]
verdamping.name = "Verdamping"

# Neerslagoverschot = neerslag - verdamping
overschot = neerslag - verdamping
overschot.name = "Neerslagoverschot"

print(f"\\nNeerslag: {len(neerslag)} dagwaarden, gemiddeld {neerslag.mean():.2f} mm/dag")
print(f"Verdamping: {len(verdamping)} dagwaarden, gemiddeld {verdamping.mean():.2f} mm/dag")
print(f"Overschot gemiddeld: {overschot.mean():.2f} mm/dag")
"""),

    markdown_cel("""## Stap 4: PASTAS Model aanmaken

We bouwen een model met:
- **Gemeten grondwaterstand** (peilbuis)
- **Stress: neerslagoverschot** (neerslag - verdamping)
- **Responsies functie: Gamma** (meest gebruikte voor grondwater)
"""),

    code_cel("""# ── Model aanmaken ──────────────────────────────────────────────
# ps.Model neemt de gemeten grondwaterstand als invoer
model = ps.Model(gws, name="B42C0133_filter001")

# ── RechargeModel toevoegen (PASTAS 1.13+) ──────────────────────
# RechargeModel combineert neerslag + verdamping direct
# (vervangt het oude StressModel2 uit eerdere PASTAS versies)
sm = ps.RechargeModel(
    prec=neerslag,          # neerslag tijdreeks (mm/dag)
    evap=verdamping,        # verdamping tijdreeks (mm/dag)
    rfunc=ps.Gamma(),       # Gamma respons functie
    recharge=ps.recharge.Linear(),  # lineair neerslagoverschot P - f*E
    name="neerslag_overschot"
)
model.add_stressmodel(sm)

# ── Model info bekijken ─────────────────────────────────────────
print(model)
print("\\nParameters voor kalibratie:")
print(model.parameters)
"""),

    markdown_cel("""## Stap 5: Model kalibreren (fitten)

PASTAS past de parameters aan zodat de gesimuleerde GWS zo goed 
mogelijk overeenkomt met de gemeten GWS.
"""),

    code_cel("""# Kalibratie uitvoeren
model.solve(
    tmin="1995-01-01",
    tmax="2004-12-31",
    report=True    # Toon statistieken
)
"""),

    markdown_cel("## Stap 6: Resultaten visualiseren"),

    code_cel("""# PASTAS heeft een ingebouwde plotfunctie
fig = model.plot(figsize=(14, 7))
plt.tight_layout()

output_pad = Path("..") / "output" / "pastas_model_B42C0133.png"
plt.savefig(output_pad, dpi=150, bbox_inches="tight")
print(f"Figuur opgeslagen: {output_pad}")
plt.show()
"""),

    markdown_cel("## Stap 7: Model statistieken en kwaliteit"),

    code_cel("""# ── Statistieken ────────────────────────────────────────────────
print("=" * 50)
print("MODEL STATISTIEKEN")
print("=" * 50)

# NSE = Nash-Sutcliffe Efficiency (1 = perfect, 0 = slecht)
nse = model.stats.nse()
evp = model.stats.evp()   # Explained Variance Percentage

print(f"Nash-Sutcliffe (NSE): {nse:.3f}")
print(f"Verklaarde variantie: {evp:.1f}%")
print()

# Gekalibreerde parameters
print("Gekalibreerde parameters:")
print(model.parameters[["optimal", "stderr"]].round(4).to_string())
print()

# Responstijd (karakteristieke tijd van grondwaterreactie)
karakteristieke_tijd = model.stressmodels["neerslag_overschot"].rfunc.to_dict()
print("Respons functie eigenschappen:")
for k, v in karakteristieke_tijd.get("parameters", {}).items():
    print(f"  {k}: {v:.4f}")
"""),

    markdown_cel("## Stap 8: Karakteristieke grondwaterstanden (GVG/GLG/GHG)"),

    code_cel("""# ── GxG berekenen ───────────────────────────────────────────────
# GVG = Gemiddeld Voorjaarsgrondwater (gemiddelde van standen op 14 mrt, 28 mrt, 14 apr)
# GLG = Gemiddeld Laagste Grondwater (gemiddelde van de 3 laagste standen per jaar)
# GHG = Gemiddeld Hoogste Grondwater (gemiddelde van de 3 hoogste standen per jaar)

gesimuleerd = model.simulate()

def bereken_gxg(reeks: pd.Series) -> dict:
    \"\"\"Berekent GHG, GLG en GVG voor een grondwaterreeks (m NAP).\"\"\"
    resultaten = {}
    
    for jaar in range(reeks.index.year.min(), reeks.index.year.max() + 1):
        jaar_data = reeks[reeks.index.year == jaar]
        
        # GVG: standen op/rondom 14 mrt, 28 mrt, 14 apr
        gvg_datums = [f"{jaar}-03-14", f"{jaar}-03-28", f"{jaar}-04-14"]
        gvg_waarden = []
        for d in gvg_datums:
            dichtstbij_idx = (jaar_data.index - pd.to_datetime(d)).abs().argmin()
            gvg_waarden.append(jaar_data.iloc[dichtstbij_idx])
        
        resultaten[jaar] = {
            "GVG": np.mean(gvg_waarden) if gvg_waarden else np.nan,
            "GHG": jaar_data.nlargest(3).mean(),
            "GLG": jaar_data.nsmallest(3).mean(),
        }
    
    return pd.DataFrame(resultaten).T


# Op basis van gemeten data
gxg_gemeten = bereken_gxg(gws)
gxg_gesim   = bereken_gxg(gesimuleerd)

print("GxG Berekening (m NAP):")
print()
print("Op basis van GEMETEN data:")
print(gxg_gemeten.round(3).to_string())
print()
print(f"GEMIDDELD: GVG={gxg_gemeten['GVG'].mean():.2f}m | "
      f"GHG={gxg_gemeten['GHG'].mean():.2f}m | "
      f"GLG={gxg_gemeten['GLG'].mean():.2f}m")

print()
print("Op basis van GESIMULEERD model:")
print(f"GEMIDDELD: GVG={gxg_gesim['GVG'].mean():.2f}m | "
      f"GHG={gxg_gesim['GHG'].mean():.2f}m | "
      f"GLG={gxg_gesim['GLG'].mean():.2f}m")
"""),

    markdown_cel("## Stap 9: Model opslaan"),

    code_cel("""# Model opslaan als .pas bestand (JSON-formaat)
model_pad = Path("..") / "output" / "model_B42C0133_filter001.pas"
model.to_file(str(model_pad))
print(f"Model opgeslagen: {model_pad}")

# Later inladen met:
# model = ps.io.load(str(model_pad))

print()
print("=" * 55)
print("Notebook 2 klaar!")
print()
print("Samenvatting:")
print(f"  Peilbuis    : B42C0133 filter 001")
print(f"  Periode     : {gws.index.min().date()} t/m {gws.index.max().date()}")
print(f"  NSE         : {model.stats.nse():.3f}")
print(f"  Model type  : Gamma respons + lineair neerslagoverschot")
print()
print("Volgende stappen:")
print("  - Vervang dummy KNMI data met echte KNMI data (scripts/haal_knmi_data.py)")
print("  - Voeg overige stresses toe (polderpeil, nabijgelegen kanalen)")
print("  - Analyseer de respons tijdconstante (snelheid grondwaterreactie)")
print("=" * 55)
"""),

]

# ══════════════════════════════════════════════════════════════════
#  Schrijf notebooks naar schijf
# ══════════════════════════════════════════════════════════════════
print("Notebooks aanmaken...")
maak_notebook("01_data_verkenning.ipynb", nb1_cellen)
maak_notebook("02_pastas_model.ipynb",    nb2_cellen)
print()
print("Klaar! Start Jupyter met:")
print("  jupyter notebook")
print("Open dan de notebooks/ map.")
