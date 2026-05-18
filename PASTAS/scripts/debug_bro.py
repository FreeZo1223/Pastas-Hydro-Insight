# -*- coding: utf-8 -*-
"""
debug_bro.py
============
Uitgebreide debugging van de BRO CSV bestanden.
Dit script laat stap-voor-stap zien hoe het bestand gelezen wordt,
zodat we exact kunnen zien waar het fout gaat.

Gebruik: python scripts/debug_bro.py
"""

import pandas as pd
from pathlib import Path

BRO_CSV = (
    Path(__file__).parent.parent
    / "Mantel_Test"
    / "BRO_Grondwatermonitoring"
    / "BRO_Grondwatermonitoringput"
    / "GMW000000069526"
    / "GLD000000073324-full.csv"
)

SEP = "=" * 60

# ── STAP 1: Ruwe bestandsinhoud lezen ────────────────────────────
print(SEP)
print("STAP 1: Ruwe bestandsinhoud (eerste 15 regels)")
print(SEP)
with open(BRO_CSV, encoding="utf-8") as f:
    regels = f.readlines()

for i, regel in enumerate(regels[:15]):
    print(f"  Regel {i+1:2d} (index {i}): {repr(regel)}")

print(f"\nTotaal aantal regels in bestand: {len(regels)}")

# ── STAP 2: Zoek de headerregel ──────────────────────────────────
print()
print(SEP)
print("STAP 2: Zoek de kolomnamenregel")
print(SEP)
header_index = None
for i, regel in enumerate(regels):
    if "tijdstip meting" in regel or "waterstand" in regel:
        print(f"  --> Header gevonden op regel {i+1} (index {i}): {repr(regel.strip())}")
        header_index = i
        break

if header_index is None:
    print("  FOUT: Header niet gevonden! Zoek naar alle regels met inhoud:")
    for i, regel in enumerate(regels):
        if regel.strip() and not all(c in ',"\n\r' for c in regel.strip()):
            print(f"  Regel {i+1:2d}: {repr(regel.strip()[:80])}")

# ── STAP 3: pd.read_csv testen met correcte skiprows ─────────────
print()
print(SEP)
print(f"STAP 3: pd.read_csv met skiprows={header_index}")
print(SEP)

if header_index is not None:
    df = pd.read_csv(
        BRO_CSV,
        skiprows=header_index,   # sla alles voor de header over
        sep=",",
        quotechar='"',
        encoding="utf-8"
    )
    # Kolomnamen opschonen
    df.columns = df.columns.str.strip().str.strip('"')
    print(f"  Kolommen: {list(df.columns)}")
    print(f"  Aantal rijen: {len(df)}")
    print(f"  Eerste 3 rijen:")
    print(df.head(3).to_string())
else:
    print("  Kan niet testen: header niet gevonden.")
    header_index = 9  # fallback

# ── STAP 4: Volledige inlaad pipeline testen ─────────────────────
print()
print(SEP)
print("STAP 4: Volledige inlaad pipeline")
print(SEP)

try:
    df = pd.read_csv(
        BRO_CSV,
        skiprows=header_index,
        sep=",",
        quotechar='"',
        encoding="utf-8"
    )
    df.columns = df.columns.str.strip().str.strip('"')

    # Verwijder lege rijen (onderaan bestand)
    df = df.dropna(subset=["waterstand"])
    print(f"  Na dropna: {len(df)} rijen")

    # Datetime parsing met tijdzone
    df["tijdstip meting"] = pd.to_datetime(
        df["tijdstip meting"], utc=True
    ).dt.tz_localize(None)

    df = df.set_index("tijdstip meting")
    df.index.name = "Datum"
    df.index = df.index.normalize()

    # Waterstand als numeriek
    gws = pd.to_numeric(df["waterstand"], errors="coerce").dropna()
    gws.name = "BRO_GWS"

    print(f"  Metingen: {len(gws)}")
    print(f"  Periode : {gws.index.min().date()} --> {gws.index.max().date()}")
    print(f"  Min/Max : {gws.min():.3f} / {gws.max():.3f} m NAP")
    print(f"  Eerste 5 waarden:")
    print(gws.head().to_string())
    print()
    print("  SUCCES: BRO CSV correct ingelezen!")

except Exception as e:
    print(f"  FOUT: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ── STAP 5: Zelfde test voor het tweede BRO bestand ──────────────
print()
print(SEP)
print("STAP 5: Tweede BRO bestand (GLD000000075843)")
print(SEP)

BRO_CSV2 = BRO_CSV.parent / "GLD000000075843-full.csv"
with open(BRO_CSV2, encoding="utf-8") as f:
    regels2 = f.readlines()

header_index2 = None
for i, regel in enumerate(regels2):
    if "tijdstip meting" in regel or "waterstand" in regel:
        print(f"  Header gevonden op regel {i+1} (index {i})")
        header_index2 = i
        break

if header_index2 != header_index:
    print(f"  LET OP: tweede bestand heeft header op andere positie ({header_index2} vs {header_index})!")
else:
    print(f"  Zelfde header positie als bestand 1: index {header_index2}")

try:
    df2 = pd.read_csv(BRO_CSV2, skiprows=header_index2, sep=",", quotechar='"', encoding="utf-8")
    df2.columns = df2.columns.str.strip().str.strip('"')
    df2 = df2.dropna(subset=["waterstand"])
    gws2 = pd.to_numeric(df2["waterstand"], errors="coerce").dropna()
    print(f"  Metingen: {len(gws2)} - SUCCES")
except Exception as e:
    print(f"  FOUT: {e}")

print()
print(SEP)
print(f"CONCLUSIE: gebruik skiprows={header_index} voor deze BRO bestanden")
print(SEP)
