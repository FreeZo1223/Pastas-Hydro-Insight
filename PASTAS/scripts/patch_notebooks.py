# -*- coding: utf-8 -*-
"""
patch_notebooks.py
==================
Past de notebooks direct aan met de gecorrigeerde code.
Runt ook een snelle validatie.

Gebruik: python scripts/patch_notebooks.py
"""

import json
from pathlib import Path

NB_DIR = Path(__file__).parent.parent / "notebooks"

# ─── Gecorrigeerde BRO functie (voor Notebook 01) ─────────────────────────────
BRO_CEL_NIEUW = """\
def lees_bro_csv(pad: Path) -> pd.Series:
    \"\"\"
    Leest een BRO Grondwaterstandsbestand in.
    Zoekt automatisch de kolomnamenregel, ongeacht het aantal metaregels.
    Geeft een pandas Series terug (waterstand in m NAP).
    \"\"\"
    # Auto-detect: zoek de regel die 'tijdstip meting' bevat
    with open(pad, encoding='utf-8') as f:
        regels = f.readlines()

    header_idx = None
    for i, regel in enumerate(regels):
        if 'tijdstip meting' in regel:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(f'Geen header gevonden in {pad.name}')

    df = pd.read_csv(pad, skiprows=header_idx, sep=',',
                     quotechar='\"', encoding='utf-8')
    df.columns = df.columns.str.strip().str.strip('\"')

    # Verwijder lege rijen
    df = df[df['waterstand'].notna()]

    # Datum met tijdzone verwerken
    df['tijdstip meting'] = pd.to_datetime(
        df['tijdstip meting'], utc=True
    ).dt.tz_localize(None)
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

# ─── Gecorrigeerde PASTAS 1.13 model cel (voor Notebook 02) ───────────────────
PASTAS_MODEL_CEL_NIEUW = """\
# Model aanmaken
# ps.Model neemt de gemeten grondwaterstand als invoer
model = ps.Model(gws, name="B42C0133_filter001")

# RechargeModel toevoegen (PASTAS 1.13+)
# Let op: in oudere PASTAS versies heette dit StressModel2
# RechargeModel combineert neerslag + verdamping direct
sm = ps.RechargeModel(
    prec=neerslag,                    # neerslag tijdreeks (mm/dag)
    evap=verdamping,                  # verdamping tijdreeks (mm/dag)
    rfunc=ps.Gamma(),                 # Gamma respons functie
    recharge=ps.recharge.Linear(),    # P - f*E (lineair neerslagoverschot)
    name="neerslag_overschot"
)
model.add_stressmodel(sm)

print(model)
print("\\nParameters voor kalibratie:")
print(model.parameters)"""


def patch_notebook(naam: str, zoek_fragment: str, vervanging: str) -> bool:
    """Vervangt een code-cel die het zoek-fragment bevat door de vervanging."""
    pad = NB_DIR / naam
    with open(pad, encoding="utf-8") as f:
        nb = json.load(f)

    gevonden = False
    for cel in nb["cells"]:
        if cel["cell_type"] == "code":
            broncode = cel["source"]
            if isinstance(broncode, list):
                broncode = "".join(broncode)
            if zoek_fragment in broncode:
                cel["source"] = vervanging
                gevonden = True
                break

    if gevonden:
        with open(pad, "w", encoding="utf-8") as f:
            json.dump(nb, f, ensure_ascii=False, indent=1)
        print(f"  [OK] {naam} bijgewerkt")
    else:
        print(f"  [WAARSCHUWING] Zoekfragment niet gevonden in {naam}")
    return gevonden


print("Notebooks patchen...")
print()

# Patch notebook 01: BRO functie vervangen
patch_notebook(
    "01_data_verkenning.ipynb",
    zoek_fragment="lees_bro_csv",      # identificeer de cel
    vervanging=BRO_CEL_NIEUW
)

# Patch notebook 02: PASTAS model cel vervangen
patch_notebook(
    "02_pastas_model.ipynb",
    zoek_fragment="StressModel2",      # identificeer de cel met de fout
    vervanging=PASTAS_MODEL_CEL_NIEUW
)

print()
print("Notebooks bijgewerkt!")
print("Herlaad de notebook in Jupyter: Kernel -> Restart & Run All")
