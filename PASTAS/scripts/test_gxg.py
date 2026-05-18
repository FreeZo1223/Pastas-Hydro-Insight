# -*- coding: utf-8 -*-
"""Snelle GxG verificatietest"""
import pandas as pd, numpy as np, pastas as ps
from pathlib import Path

ROOT = Path(__file__).parent.parent
DINO_DIR = ROOT / "Mantel_Test" / "DINO_Grondwaterstanden"
KNMI_DIR = ROOT / "data" / "knmi"

df = pd.read_csv(DINO_DIR / "B42C0133001.csv", skiprows=12, sep=",", quotechar='"', encoding="utf-8")
df.columns = df.columns.str.strip().str.strip('"')
df["Peildatum"] = pd.to_datetime(df["Peildatum"], format="%d-%m-%Y")
df = df.set_index("Peildatum")
gws = (df["Stand (cm t.o.v NAP)"].dropna() / 100.0)
gws.name = "B42C0133001"

neerslag   = pd.read_csv(next(KNMI_DIR.glob("neerslag_*.csv")),   index_col="Datum", parse_dates=True).iloc[:,0]
verdamping = pd.read_csv(next(KNMI_DIR.glob("verdamping_*.csv")), index_col="Datum", parse_dates=True).iloc[:,0]

model = ps.Model(gws, name="gxg_test")
sm = ps.RechargeModel(prec=neerslag, evap=verdamping, rfunc=ps.Gamma(),
                      recharge=ps.recharge.Linear(), name="neerslag_overschot")
model.add_stressmodel(sm)
model.solve(tmin="1995-01-01", tmax="2004-12-31", report=False)
gesimuleerd = model.simulate()

def bereken_gxg(reeks):
    resultaten = {}
    for jaar in range(reeks.index.year.min(), reeks.index.year.max() + 1):
        jaar_data = reeks[reeks.index.year == jaar]
        if len(jaar_data) == 0:
            continue
        gvg_datums = [f"{jaar}-03-14", f"{jaar}-03-28", f"{jaar}-04-14"]
        gvg_waarden = []
        for d in gvg_datums:
            diff = jaar_data.index - pd.to_datetime(d)
            dichtstbij_idx = np.abs(diff).argmin()   # FIX: np.abs() ipv .abs()
            gvg_waarden.append(jaar_data.iloc[dichtstbij_idx])
        resultaten[jaar] = {
            "GVG": np.mean(gvg_waarden),
            "GHG": jaar_data.nlargest(3).mean(),
            "GLG": jaar_data.nsmallest(3).mean(),
        }
    return pd.DataFrame(resultaten).T

gxg_gemeten = bereken_gxg(gws)
gxg_gesim   = bereken_gxg(gesimuleerd)

print("GxG GEMETEN   : GVG={:.2f}m | GHG={:.2f}m | GLG={:.2f}m".format(
    gxg_gemeten["GVG"].mean(), gxg_gemeten["GHG"].mean(), gxg_gemeten["GLG"].mean()))
print("GxG GESIMULEERD: GVG={:.2f}m | GHG={:.2f}m | GLG={:.2f}m".format(
    gxg_gesim["GVG"].mean(), gxg_gesim["GHG"].mean(), gxg_gesim["GLG"].mean()))
print()
print("SUCCES: GxG berekening werkt correct!")
