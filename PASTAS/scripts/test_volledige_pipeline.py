# -*- coding: utf-8 -*-
"""
test_volledige_pipeline.py
==========================
Test de volledige data pipeline zoals die in de notebooks gebruikt wordt.
Als dit script succesvol draait, werken de notebooks ook.

Gebruik: python scripts/test_volledige_pipeline.py
"""

import sys
import traceback
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # geen scherm nodig voor headless testen
import matplotlib.pyplot as plt
import pastas as ps
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "Mantel_Test"
DINO_DIR = DATA_DIR / "DINO_Grondwaterstanden"
BRO_DIR  = DATA_DIR / "BRO_Grondwatermonitoring" / "BRO_Grondwatermonitoringput" / "GMW000000069526"
KNMI_DIR = ROOT / "data" / "knmi"
OUTPUT   = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)

fouten = []

def stap(beschrijving):
    print(f"\n{'-'*55}")
    print(f"  {beschrijving}")
    print(f"{'-'*55}")

def ok(msg):   print(f"  [OK]   {msg}")
def fout(msg): print(f"  [FOUT] {msg}"); fouten.append(msg)

print("=" * 55)
print("  Volledige pipeline test — PASTAS Peilbuis B42C0133")
print("=" * 55)

# ────────────────────────────────────────────────────────────────
# DINO INLADING
# ────────────────────────────────────────────────────────────────
stap("1. DINO CSV inladen")

def lees_dino_csv(pad: Path) -> pd.Series:
    df = pd.read_csv(pad, skiprows=12, sep=",", quotechar='"', encoding="utf-8")
    df.columns = df.columns.str.strip().str.strip('"')
    df["Peildatum"] = pd.to_datetime(df["Peildatum"], format="%d-%m-%Y")
    df = df.set_index("Peildatum")
    df.index.name = "Datum"
    gws = df["Stand (cm t.o.v NAP)"].dropna() / 100.0
    gws.name = pad.stem
    return gws

try:
    gws_001 = lees_dino_csv(DINO_DIR / "B42C0133001.csv")
    gws_002 = lees_dino_csv(DINO_DIR / "B42C0133002.csv")
    ok(f"Filter 001: {len(gws_001)} metingen, {gws_001.index.min().date()} - {gws_001.index.max().date()}")
    ok(f"Filter 002: {len(gws_002)} metingen, range [{gws_002.min():.2f}, {gws_002.max():.2f}] m NAP")
except Exception as e:
    fout(f"DINO inladen mislukt: {e}")
    traceback.print_exc()

# ────────────────────────────────────────────────────────────────
# BRO INLADING — auto-detect headerregel
# ────────────────────────────────────────────────────────────────
stap("2. BRO CSV inladen (auto-detect header)")

def lees_bro_csv(pad: Path) -> pd.Series:
    """
    Leest BRO GLD CSV robuust in door de headerregel automatisch te zoeken.
    Werkt ongeacht hoeveel metaregels er boven staan.
    """
    # Zoek de headerregel (bevat "tijdstip meting")
    with open(pad, encoding="utf-8") as f:
        regels = f.readlines()

    header_idx = None
    for i, regel in enumerate(regels):
        if "tijdstip meting" in regel:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(f"Geen header gevonden in {pad.name}")

    # Lees CSV met de gevonden header positie
    df = pd.read_csv(
        pad,
        skiprows=header_idx,   # sla alles voor header over
        sep=",",
        quotechar='"',
        encoding="utf-8"
    )
    df.columns = df.columns.str.strip().str.strip('"')

    # Verwijder lege/NaN rijen op de waterstand kolom
    df = df[df["waterstand"].notna()]
    df = df[df["waterstand"].astype(str).str.strip() != ""]

    # Datetime parsing (inclusief tijdzone)
    df["tijdstip meting"] = pd.to_datetime(df["tijdstip meting"], utc=True).dt.tz_localize(None)
    df = df.set_index("tijdstip meting")
    df.index.name = "Datum"
    df.index = df.index.normalize()

    # Waterstand naar float
    gws = pd.to_numeric(df["waterstand"], errors="coerce").dropna()
    gws.name = pad.stem
    return gws

try:
    bro_73324 = lees_bro_csv(BRO_DIR / "GLD000000073324-full.csv")
    bro_75843 = lees_bro_csv(BRO_DIR / "GLD000000075843-full.csv")
    ok(f"BRO 73324: {len(bro_73324)} metingen, [{bro_73324.min():.2f}, {bro_73324.max():.2f}] m NAP")
    ok(f"BRO 75843: {len(bro_75843)} metingen, [{bro_75843.min():.2f}, {bro_75843.max():.2f}] m NAP")
except Exception as e:
    fout(f"BRO inladen mislukt: {e}")
    traceback.print_exc()

# ────────────────────────────────────────────────────────────────
# KNMI DATA
# ────────────────────────────────────────────────────────────────
stap("3. KNMI data inladen")

try:
    neerslag_pad   = next(KNMI_DIR.glob("neerslag_*.csv"))
    verdamping_pad = next(KNMI_DIR.glob("verdamping_*.csv"))
    neerslag   = pd.read_csv(neerslag_pad,   index_col="Datum", parse_dates=True).iloc[:, 0]
    verdamping = pd.read_csv(verdamping_pad, index_col="Datum", parse_dates=True).iloc[:, 0]
    neerslag.name   = "Neerslag"
    verdamping.name = "Verdamping"
    ok(f"Neerslag: {len(neerslag)} dagwaarden, gem. {neerslag.mean():.2f} mm/dag")
    ok(f"Verdamping: {len(verdamping)} dagwaarden, gem. {verdamping.mean():.2f} mm/dag")
except Exception as e:
    fout(f"KNMI inladen mislukt: {e}")
    traceback.print_exc()

# ────────────────────────────────────────────────────────────────
# VISUALISATIE
# ────────────────────────────────────────────────────────────────
stap("4. Tijdreeks grafiek genereren")

try:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    ax1.plot(gws_001.index, gws_001.values, color="#1565C0", lw=1.5, marker=".", ms=4, label="DINO filter 001")
    ax1.plot(bro_73324.index, bro_73324.values, color="#E53935", lw=1.5, marker=".", ms=4, alpha=0.7, label="BRO filter 2")
    ax1.set_ylabel("Grondwaterstand [m NAP]")
    ax1.set_title("Peilbuis B42C0133 — Grondwaterstanden 1995–2004")
    ax1.legend(); ax1.grid(True, alpha=0.3)
    ax2.plot(gws_002.index, gws_002.values, color="#2E7D32", lw=1.5, marker=".", ms=4, label="DINO filter 002")
    ax2.set_ylabel("Grondwaterstand [m NAP]"); ax2.legend(); ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    fig_pad = OUTPUT / "tijdreeks_peilbuis_B42C0133.png"
    plt.savefig(fig_pad, dpi=150, bbox_inches="tight")
    plt.close()
    ok(f"Grafiek opgeslagen: {fig_pad}")
except Exception as e:
    fout(f"Grafiek mislukt: {e}")
    traceback.print_exc()

# ────────────────────────────────────────────────────────────────
# PASTAS MODEL
# ────────────────────────────────────────────────────────────────
stap("5. PASTAS model bouwen en kalibreren")

try:
    model = ps.Model(gws_001, name="B42C0133_filter001")
    rm = ps.recharge.Linear()
    sm = ps.RechargeModel(
        prec=neerslag,
        evap=verdamping,
        rfunc=ps.Gamma(),
        recharge=ps.recharge.Linear(),
        name="neerslag_overschot"
    )
    model.add_stressmodel(sm)
    ok("Model aangemaakt")

    model.solve(tmin="1995-01-01", tmax="2004-12-31", report=False)
    nse = model.stats.nse()
    evp = model.stats.evp()
    ok(f"Kalibratie geslaagd: NSE={nse:.3f}, Variantie={evp:.1f}%")

    fig2 = model.plot(figsize=(14, 7))
    plt.tight_layout()
    model_fig = OUTPUT / "pastas_model_B42C0133.png"
    plt.savefig(model_fig, dpi=150, bbox_inches="tight")
    plt.close()
    ok(f"Model grafiek opgeslagen: {model_fig}")

    model_pas = OUTPUT / "model_B42C0133_filter001.pas"
    model.to_file(str(model_pas))
    ok(f"Model opgeslagen: {model_pas}")

except Exception as e:
    fout(f"PASTAS model mislukt: {e}")
    traceback.print_exc()

# ────────────────────────────────────────────────────────────────
# EINDRESULTAAT
# ────────────────────────────────────────────────────────────────
print()
print("=" * 55)
if fouten:
    print(f"  RESULTAAT: {len(fouten)} FOUT(EN) GEVONDEN")
    for f in fouten:
        print(f"    - {f}")
    sys.exit(1)
else:
    print("  RESULTAAT: ALLE STAPPEN GESLAAGD!")
    print("  De notebooks zijn klaar voor gebruik.")
print("=" * 55)
