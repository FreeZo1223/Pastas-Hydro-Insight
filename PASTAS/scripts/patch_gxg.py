# -*- coding: utf-8 -*-
"""
patch_gxg.py
============
Past de GxG bereken_gxg functie in notebook 02 aan.
Fix: gebruik np.abs() ipv TimedeltaIndex.abs() (werkt niet in pandas 2.x)

Gebruik: python scripts/patch_gxg.py
"""

import json
from pathlib import Path

NB_PAD = Path(__file__).parent.parent / "notebooks" / "02_pastas_model.ipynb"

GXG_CEL_NIEUW = """\
# GxG berekenen
# GVG = Gemiddeld Voorjaarsgrondwater (standen op 14 mrt, 28 mrt, 14 apr)
# GLG = Gemiddeld Laagste Grondwater  (gemiddelde 3 laagste standen per jaar)
# GHG = Gemiddeld Hoogste Grondwater  (gemiddelde 3 hoogste standen per jaar)

import numpy as np

gesimuleerd = model.simulate()

def bereken_gxg(reeks: pd.Series) -> dict:
    \"\"\"Berekent GHG, GLG en GVG voor een grondwaterreeks (m NAP).\"\"\"
    resultaten = {}

    for jaar in range(reeks.index.year.min(), reeks.index.year.max() + 1):
        jaar_data = reeks[reeks.index.year == jaar]
        if len(jaar_data) == 0:
            continue

        # GVG: standen op/rondom 14 mrt, 28 mrt, 14 apr
        gvg_datums = [f"{jaar}-03-14", f"{jaar}-03-28", f"{jaar}-04-14"]
        gvg_waarden = []
        for d in gvg_datums:
            # np.abs() werkt op TimedeltaIndex in alle pandas versies
            diff = jaar_data.index - pd.to_datetime(d)
            dichtstbij_idx = np.abs(diff).argmin()
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
      f"GLG={gxg_gesim['GLG'].mean():.2f}m")"""


def patch_notebook():
    with open(NB_PAD, encoding="utf-8") as f:
        nb = json.load(f)

    gevonden = False
    for cel in nb["cells"]:
        if cel["cell_type"] == "code":
            broncode = cel["source"]
            if isinstance(broncode, list):
                broncode = "".join(broncode)
            if "bereken_gxg" in broncode:
                cel["source"] = GXG_CEL_NIEUW
                gevonden = True
                break

    if gevonden:
        with open(NB_PAD, "w", encoding="utf-8") as f:
            json.dump(nb, f, ensure_ascii=False, indent=1)
        print("[OK] GxG cel gepatcht in 02_pastas_model.ipynb")
    else:
        print("[WAARSCHUWING] bereken_gxg niet gevonden in notebook")
    return gevonden


patch_notebook()
print()
print("Herlaad in Jupyter: Kernel -> Restart & Run All")
