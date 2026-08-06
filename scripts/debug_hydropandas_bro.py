"""
debug_hydropandas_bro.py
========================
Uitgebreide test van de Hydropandas API voor BRO grondwaterdata.
Stap voor stap zodat we exact kunnen zien waar het fout gaat.

Gebruik: python debug_hydropandas_bro.py
"""

import traceback
import sys
import pandas as pd

BRO_ID = "GMW000000069526"  # de peilbuis uit het project

print("=" * 60)
print(f"  Hydropandas BRO debug voor: {BRO_ID}")
print(f"  Python versie: {sys.version}")
print("=" * 60)

# ── Stap 1: Controleer versie ─────────────────────────────────────
print("\n[1] Hydropandas versie...")
try:
    import hydropandas as hpd
    print(f"    hydropandas versie: {hpd.__version__}")
except Exception as e:
    print(f"    FOUT: {e}")
    sys.exit(1)

# ── Stap 2: Inspecteer beschikbare functies ───────────────────────
print("\n[2] Beschikbare klassen/functies in hydropandas:")
attrs = [a for a in dir(hpd) if not a.startswith("_")]
print("   ", attrs)

# ── Stap 3a: Probeer hpd.GroundwaterObs.from_bro ─────────────────
print(f"\n[3a] hpd.GroundwaterObs.from_bro(bro_id='{BRO_ID}')...")
try:
    obs = hpd.GroundwaterObs.from_bro(bro_id=BRO_ID)
    print(f"    Type: {type(obs)}")
    print(f"    Lengte: {len(obs)}")
    print(f"    Kolommen: {list(obs.columns) if hasattr(obs, 'columns') else 'geen'}")
    print(f"    Index: {obs.index[:3]}")
    print(f"    Eerste waarden:\n{obs.head(3)}")
    print(f"    x={getattr(obs, 'x', 'N/A')}, y={getattr(obs, 'y', 'N/A')}")

    # Probeer de tijdreeks te extraheren
    print("\n    Extraheren van tijdreeks...")
    if hasattr(obs, "iloc"):
        col = obs.columns[0] if hasattr(obs, "columns") and len(obs.columns) > 0 else None
        if col:
            gws = obs[col].dropna()
            print(f"    Tijdreeks kolom '{col}': {len(gws)} waarden")
            print(f"    Min: {gws.min():.3f}, Max: {gws.max():.3f}")
            print(f"    Periode: {gws.index.min()} – {gws.index.max()}")
except Exception as e:
    print(f"    FOUT: {type(e).__name__}: {e}")
    traceback.print_exc()

# ── Stap 3b: Probeer hpd.read_bro ─────────────────────────────────
print(f"\n[3b] hpd.read_bro(bro_id='{BRO_ID}')...")
try:
    obs2 = hpd.read_bro(bro_id=BRO_ID)
    print(f"    Type: {type(obs2)}")
    print(f"    Lengte: {len(obs2)}")
    print(f"    Eerste rijen:\n{obs2.head(3)}")
except AttributeError:
    print("    read_bro() niet beschikbaar in deze versie.")
except Exception as e:
    print(f"    FOUT: {type(e).__name__}: {e}")
    traceback.print_exc()

# ── Stap 3c: Probeer ObsCollection.from_bro ──────────────────────
print(f"\n[3c] hpd.ObsCollection.from_bro(bro_id='{BRO_ID}')...")
try:
    oc = hpd.ObsCollection.from_bro(bro_id=BRO_ID)
    print(f"    Type: {type(oc)}")
    print(f"    Lengte: {len(oc)}")
    print(f"    Kolommen: {list(oc.columns)}")
    print(f"    Index:\n{oc.index.tolist()}")

    for naam in oc.index:
        print(f"\n    Serie '{naam}':")
        obs3 = oc.loc[naam, "obs"]
        print(f"      Type: {type(obs3)}")
        print(f"      Lengte: {len(obs3)}")
        if len(obs3) > 0:
            print(f"      Eerste:\n{obs3.head(2)}")
except AttributeError:
    print("    ObsCollection.from_bro() niet beschikbaar.")
except Exception as e:
    print(f"    FOUT: {type(e).__name__}: {e}")
    traceback.print_exc()

# ── Stap 4: help() uitvoer van GroundwaterObs ────────────────────
print("\n[4] Handtekening van GroundwaterObs.from_bro:")
try:
    import inspect
    sig = inspect.signature(hpd.GroundwaterObs.from_bro)
    print(f"    {sig}")
    # Toon de docstring (eerste 500 tekens)
    doc = hpd.GroundwaterObs.from_bro.__doc__
    if doc:
        print(f"    Docstring:\n{doc[:600]}")
except Exception as e:
    print(f"    FOUT: {e}")

# ── Stap 5: ObsCollection.from_bro handtekening ──────────────────
print("\n[5] Handtekening van ObsCollection.from_bro:")
try:
    sig2 = inspect.signature(hpd.ObsCollection.from_bro)
    print(f"    {sig2}")
    doc2 = hpd.ObsCollection.from_bro.__doc__
    if doc2:
        print(f"    Docstring:\n{doc2[:400]}")
except Exception as e:
    print(f"    FOUT: {e}")

print("\n" + "=" * 60)
print("  Debug klaar!")
print("=" * 60)
