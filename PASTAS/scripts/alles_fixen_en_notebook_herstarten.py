"""
alles_fixen_en_notebook_herstarten.py
======================================
Past alle bekende bugs in één keer toe en herstart Jupyter.

Fixes:
  1. BRO CSV: auto-detect header (ipv vaste skiprows=10)
  2. PASTAS 1.13: RechargeModel ipv StressModel2
  3. GxG: np.abs() ipv TimedeltaIndex.abs()

Gebruik: python scripts/alles_fixen_en_notebook_herstarten.py
"""

import json, subprocess, sys
from pathlib import Path

NB_DIR = Path(__file__).parent.parent / "notebooks"

# ══════════════════════════════════════════════════════════════════════
#  Alle gecorrigeerde cellen
# ══════════════════════════════════════════════════════════════════════

BRO_CEL = """\
def lees_bro_csv(pad: Path) -> pd.Series:
    \"\"\"
    Leest een BRO Grondwaterstandsbestand in.
    Zoekt automatisch de kolomnamenregel (regel met 'tijdstip meting').
    Geeft een pandas Series terug (waterstand in m NAP).
    \"\"\"
    with open(pad, encoding='utf-8') as f:
        regels = f.readlines()
    header_idx = next((i for i, r in enumerate(regels) if 'tijdstip meting' in r), None)
    if header_idx is None:
        raise ValueError(f'Geen header gevonden in {pad.name}')
    df = pd.read_csv(pad, skiprows=header_idx, sep=',', quotechar='\"', encoding='utf-8')
    df.columns = df.columns.str.strip().str.strip('\"')
    df = df[df['waterstand'].notna()]
    df['tijdstip meting'] = pd.to_datetime(df['tijdstip meting'], utc=True).dt.tz_localize(None)
    df = df.set_index('tijdstip meting')
    df.index.name = 'Datum'
    df.index = df.index.normalize()
    gws = pd.to_numeric(df['waterstand'], errors='coerce').dropna()
    gws.name = pad.stem
    return gws


# Lees de twee BRO bestanden
bro_73324 = lees_bro_csv(BRO_DIR / "GLD000000073324-full.csv")
bro_75843 = lees_bro_csv(BRO_DIR / "GLD000000075843-full.csv")

print(f"BRO GLD000000073324 geladen: {len(bro_73324)} metingen")
print(f"  Periode: {bro_73324.index.min().date()} tot {bro_73324.index.max().date()}")
print(f"  Min/Max: {bro_73324.min():.2f} / {bro_73324.max():.2f} m NAP")
print()
print(f"BRO GLD000000075843 geladen: {len(bro_75843)} metingen")
print(f"  Periode: {bro_75843.index.min().date()} tot {bro_75843.index.max().date()}")"""

PASTAS_MODEL_CEL = """\
# Model aanmaken
model = ps.Model(gws, name="B42C0133_filter001")

# RechargeModel toevoegen (PASTAS 1.13+)
# Let op: in eerdere PASTAS versies (<1.0) heette dit StressModel2
sm = ps.RechargeModel(
    prec=neerslag,
    evap=verdamping,
    rfunc=ps.Gamma(),
    recharge=ps.recharge.Linear(),
    name="neerslag_overschot"
)
model.add_stressmodel(sm)

print(model)
print("\\nParameters voor kalibratie:")
print(model.parameters)"""

GXG_CEL = """\
# GxG berekenen
# GVG = Gemiddeld Voorjaarsgrondwater (standen op 14 mrt, 28 mrt, 14 apr)
# GLG = Gemiddeld Laagste Grondwater  (gemiddelde 3 laagste standen per jaar)
# GHG = Gemiddeld Hoogste Grondwater  (gemiddelde 3 hoogste standen per jaar)

import numpy as np   # np.abs() is nodig voor pandas 2.x compatibiliteit

gesimuleerd = model.simulate()

def bereken_gxg(reeks: pd.Series) -> pd.DataFrame:
    \"\"\"Berekent GHG, GLG en GVG voor een grondwaterreeks (m NAP).\"\"\"
    resultaten = {}
    for jaar in range(reeks.index.year.min(), reeks.index.year.max() + 1):
        jaar_data = reeks[reeks.index.year == jaar]
        if len(jaar_data) == 0:
            continue
        # GVG-datums: 14 mrt, 28 mrt, 14 apr
        gvg_datums = [f"{jaar}-03-14", f"{jaar}-03-28", f"{jaar}-04-14"]
        gvg_waarden = []
        for d in gvg_datums:
            diff = jaar_data.index - pd.to_datetime(d)
            dichtstbij_idx = np.abs(diff).argmin()   # np.abs() voor pandas 2.x
            gvg_waarden.append(jaar_data.iloc[dichtstbij_idx])
        resultaten[jaar] = {
            "GVG": np.mean(gvg_waarden),
            "GHG": jaar_data.nlargest(3).mean(),
            "GLG": jaar_data.nsmallest(3).mean(),
        }
    return pd.DataFrame(resultaten).T


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
      f"GLG={gxg_gesim['GLG'].mean():.2f}m")"""

# ══════════════════════════════════════════════════════════════════════
#  Patch functie
# ══════════════════════════════════════════════════════════════════════

PATCHES = {
    "01_data_verkenning.ipynb": [
        ("lees_bro_csv",    BRO_CEL),
    ],
    "02_pastas_model.ipynb": [
        ("RechargeModel\n    prec=neerslag",  PASTAS_MODEL_CEL),
        ("StressModel2",                       PASTAS_MODEL_CEL),   # als patch_notebooks al gedraaid is
        ("bereken_gxg",    GXG_CEL),
    ],
}

for bestand, wijzigingen in PATCHES.items():
    pad = NB_DIR / bestand
    with open(pad, encoding="utf-8") as f:
        nb = json.load(f)

    for zoekterm, nieuw in wijzigingen:
        for cel in nb["cells"]:
            if cel["cell_type"] != "code":
                continue
            src = "".join(cel["source"]) if isinstance(cel["source"], list) else cel["source"]
            if zoekterm in src:
                cel["source"] = nieuw
                print(f"  [OK] '{zoekterm[:30]}...' gepatcht in {bestand}")
                break

    with open(pad, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)

print()
print("Alle patches toegepast!")
print()
print("Nu Jupyter notebook herstarten...")
print("Sluit de browser-tab van de notebook.")
print("Druk Ctrl+C in de Jupyter terminal.")
print("Start opnieuw met: jupyter notebook notebooks/02_pastas_model.ipynb")
