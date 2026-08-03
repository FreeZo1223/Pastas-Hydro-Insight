"""
genereer_knmi_dummy.py
======================
Genereert realistische KNMI neerslag- en verdampingsdata voor 
de Zeelandse locatie van peilbuis B42C0133 (1995-2004).

Gebaseerd op klimatologische normen KNMI station Terneuzen (742):
- Gemiddelde jaarlijkse neerslag Zeeland: ~760 mm/jaar (~2.1 mm/dag)
- Gemiddelde referentieverdamping Makkink: ~490 mm/jaar (~1.3 mm/dag)

Dit script genereert data die statistisch vergelijkbaar is met
echte KNMI-data voor deze regio en periode.

Gebruik:
  python scripts/genereer_knmi_dummy.py
"""

import numpy as np
import pandas as pd
from pathlib import Path

# ──────────────────────────────────────────────────────────────────
# Configuratie
# ──────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "knmi"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

np.random.seed(42)  # Voor reproduceerbaarheid

# Volledige periode peilbuisreeks
PERIODEN = pd.date_range("1995-01-01", "2004-12-31", freq="D")
N = len(PERIODEN)

# ──────────────────────────────────────────────────────────────────
# Neerslag: realistisch gesimuleerd voor Zeeland
# ──────────────────────────────────────────────────────────────────
# Zeeland heeft een gematigd zeeklimaat: natter in winter, droger in zomer
# Maandelijkse gemiddelden (mm/dag) op basis van KNMI klimaatdata
MAAND_NEERSLAG = {
    1:  2.6,  # jan (natter)
    2:  2.2,
    3:  2.3,
    4:  1.7,
    5:  1.9,
    6:  2.1,
    7:  2.2,
    8:  2.1,
    9:  2.4,
    10: 3.0,  # okt (natst)
    11: 2.9,
    12: 2.8,
}

# Neerslag is gamma-verdeeld (altijd >= 0, met staart naar rechts)
neerslag_vals = np.zeros(N)
maanden = PERIODEN.month

for maand, gemiddelde in MAAND_NEERSLAG.items():
    mask = maanden == maand
    n_dagen = mask.sum()
    if n_dagen > 0:
        # Gamma verdeling: ~60% kans op droge dag, 40% kans op neerslag
        natte_dagen = np.random.binomial(1, 0.4, n_dagen).astype(bool)
        regen_mm = np.where(
            natte_dagen,
            np.random.gamma(shape=1.0, scale=gemiddelde / 0.4, size=n_dagen),
            0.0
        )
        # Clip extreme waarden
        regen_mm = np.clip(regen_mm, 0, 50)
        neerslag_vals[mask] = regen_mm

neerslag = pd.Series(neerslag_vals, index=PERIODEN, name="Neerslag_mm")
neerslag = neerslag.round(1)

# ──────────────────────────────────────────────────────────────────
# Verdamping: Makkink referentiegewasverdamping Zeeland
# ──────────────────────────────────────────────────────────────────
# Sterk seizoensgebonden: laag in winter, hoog in zomer
MAAND_VERDAMPING = {
    1:  0.2,
    2:  0.4,
    3:  1.0,
    4:  1.8,
    5:  2.8,
    6:  3.5,
    7:  3.7,
    8:  3.2,
    9:  2.2,
    10: 1.1,
    11: 0.4,
    12: 0.1,
}

verdamping_vals = np.zeros(N)
for maand, gemiddelde in MAAND_VERDAMPING.items():
    mask = maanden == maand
    n_dagen = mask.sum()
    if n_dagen > 0:
        # Verdamping heeft klein dagelijks variatie (afhankelijk van zonneschijn)
        dagvariatie = np.random.normal(loc=0, scale=gemiddelde * 0.2, size=n_dagen)
        ev = (gemiddelde + dagvariatie).clip(0)
        verdamping_vals[mask] = ev

verdamping = pd.Series(verdamping_vals, index=PERIODEN, name="Verdamping_mm")
verdamping = verdamping.round(2)

# ──────────────────────────────────────────────────────────────────
# Opslaan als CSV
# ──────────────────────────────────────────────────────────────────
neerslag_pad = OUTPUT_DIR / "neerslag_knmi_zeeland_simulatie.csv"
verdamping_pad = OUTPUT_DIR / "verdamping_knmi_zeeland_simulatie.csv"

neerslag.to_csv(neerslag_pad, sep=",", header=True, index_label="Datum")
verdamping.to_csv(verdamping_pad, sep=",", header=True, index_label="Datum")

# ──────────────────────────────────────────────────────────────────
# Statistieken afdrukken
# ──────────────────────────────────────────────────────────────────
print("=" * 55)
print("Gesimuleerde KNMI Data - Zeeland (1995-2004)")
print("Gebaseerd op klimaatnormen station Terneuzen (742)")
print("=" * 55)
print(f"\nNeerslag:")
print(f"  Periode  : {PERIODEN[0].date()} tot {PERIODEN[-1].date()}")
print(f"  Totaal   : {neerslag.sum():.0f} mm over {N} dagen")
print(f"  Jaargemiddeld: {neerslag.sum() / 10:.0f} mm/jaar")
print(f"  Droge dagen  : {(neerslag == 0).sum()} ({100*(neerslag==0).mean():.0f}%)")
print(f"  Opgeslagen: {neerslag_pad}")

print(f"\nVerdamping (Makkink EV24):")
print(f"  Jaargemiddeld: {verdamping.sum() / 10:.0f} mm/jaar")
print(f"  Opgeslagen: {verdamping_pad}")

print("\nNOTE: Dit zijn gesimuleerde waarden (KNMI API tijdelijk offline).")
print("      Vervang later door echte KNMI data via haal_knmi_data.py")
