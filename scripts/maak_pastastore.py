# -*- coding: utf-8 -*-
"""
maak_pastastore.py
==================
Maakt een PastaStore aan met de grondwaterdata en PASTAS modellen
uit het lopende PASTAS analyse project.

De store wordt opgeslagen als een Zarr database, geschikt voor
het PastasDash dashboard.

Gebruik:
    python scripts/maak_pastastore.py

Daarna pastasdash starten via:
    conda activate pastasdash
    pastasdash
... en de store laden via "Load Pastastore" -> output/pastastore/
"""

import pandas as pd
import numpy as np
import pastas as ps
import pastastore as pst
from pathlib import Path

ROOT = Path(__file__).parent.parent
DINO_DIR = ROOT / "Mantel_Test" / "DINO_Grondwaterstanden"
BRO_DIR  = (ROOT / "Mantel_Test" / "BRO_Grondwatermonitoring"
            / "BRO_Grondwatermonitoringput" / "GMW000000069526")
KNMI_DIR = ROOT / "data" / "knmi"
STORE_PAD = ROOT / "output" / "pastastore"

print("=" * 55)
print("  PastaStore aanmaken voor PastasDash")
print("=" * 55)

# ── 1. Store aanmaken ────────────────────────────────────────
STORE_PAD.mkdir(parents=True, exist_ok=True)
conn = pst.PasConnector("B42C0133", str(STORE_PAD))
pstore = pst.PastaStore("B42C0133", conn)
print(f"\n[OK] PastaStore aangemaakt: {STORE_PAD}")

# ── 2. Grondwater tijdreeks (DINO) ───────────────────────────
print("\n[..] DINO data inladen...")
df = pd.read_csv(
    DINO_DIR / "B42C0133001.csv",
    skiprows=12, sep=",", quotechar='"', encoding="utf-8"
)
df.columns = df.columns.str.strip().str.strip('"')
df["Peildatum"] = pd.to_datetime(df["Peildatum"], format="%d-%m-%Y")
df = df.set_index("Peildatum")
df.index.name = "Datum"
gws = (df["Stand (cm t.o.v NAP)"].dropna() / 100.0)
gws.name = "B42C0133_001"

pstore.add_oseries(gws, "B42C0133_001", metadata={
    "x": 85000, "y": 385000,  # fictieve RD-coördinaten (Zeeland)
    "screen_top": -0.5,
    "screen_bottom": -3.0,
    "source": "DINO",
    "filter": "001",
})
print(f"[OK] Grondwater opgeslagen: {len(gws)} metingen")

# ── 3. Neerslag en verdamping (KNMI) ─────────────────────────
print("\n[..] KNMI data inladen...")
neerslag   = pd.read_csv(
    next(KNMI_DIR.glob("neerslag_*.csv")),
    index_col="Datum", parse_dates=True
).iloc[:, 0]
verdamping = pd.read_csv(
    next(KNMI_DIR.glob("verdamping_*.csv")),
    index_col="Datum", parse_dates=True
).iloc[:, 0]
neerslag.name   = "P_KNMI"
verdamping.name = "E_KNMI"

pstore.add_stress(neerslag, "P_KNMI", kind="prec",
                  metadata={"x": 85000, "y": 385000})
pstore.add_stress(verdamping, "E_KNMI", kind="evap",
                  metadata={"x": 85000, "y": 385000})
print(f"[OK] Neerslag opgeslagen: {len(neerslag)} dagwaarden")
print(f"[OK] Verdamping opgeslagen: {len(verdamping)} dagwaarden")

# ── 4. PASTAS model bouwen en opslaan ────────────────────────
print("\n[..] PASTAS model bouwen...")
model = ps.Model(gws, name="B42C0133_001")
sm = ps.RechargeModel(
    prec=neerslag,
    evap=verdamping,
    rfunc=ps.Gamma(),
    recharge=ps.recharge.Linear(),
    name="neerslag_overschot"
)
model.add_stressmodel(sm)
model.solve(tmin="1995-01-01", tmax="2004-12-31", report=False)

nse = model.stats.nse()
evp = model.stats.evp()
print(f"[OK] Kalibratie: NSE={nse:.3f}, EVP={evp:.1f}%")

pstore.add_model(model)
print("[OK] Model opgeslagen in PastaStore")

# ── 5. Overzicht ─────────────────────────────────────────────
print()
print("=" * 55)
print(f"  PastaStore klaar!")
print(f"  Locatie: {STORE_PAD}")
print()
print(f"  Tijdreeksen : {pstore.oseries.index.tolist()}")
print(f"  Stressoren  : {pstore.stresses.index.tolist()}")
print(f"  Modellen    : {pstore.models}")
print()
print("  Start dashboard:")
print("    conda activate pastasdash")
print("    pastasdash")
print("  Open: http://127.0.0.1:8050")
print("  Klik 'Load Pastastore' en navigeer naar:")
print(f"    {STORE_PAD}")
print("=" * 55)
