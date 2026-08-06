# -*- coding: utf-8 -*-
"""
maak_pastastore_snel.py
========================
Maakt een PastaStore aan met DINO grondwaterdata en KNMI klimaatdata.

Gebruik:
    python scripts/maak_pastastore_snel.py

Daarna pastasdash starten:
    conda activate pastasdash
    pastasdash
... en via "Load Pastastore" -> output/pastastore/ laden.
"""

import pandas as pd
import pastastore as pst
from pathlib import Path


def maak_store():
    ROOT = Path(__file__).parent.parent
    DINO_DIR = ROOT / "Mantel_Test" / "DINO_Grondwaterstanden"
    KNMI_DIR = ROOT / "data" / "knmi"
    STORE_PAD = ROOT / "output" / "pastastore"

    print("PastaStore aanmaken...")
    STORE_PAD.mkdir(parents=True, exist_ok=True)

    conn   = pst.PasConnector("B42C0133", str(STORE_PAD))
    pstore = pst.PastaStore(conn, "B42C0133")

    # ── DINO grondwaterstanden ────────────────────────────────
    print("\nDINO data inladen...")
    for csv in sorted(DINO_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(csv, skiprows=12, sep=",",
                             quotechar='"', encoding="utf-8")
            df.columns = df.columns.str.strip().str.strip('"')
            df["Peildatum"] = pd.to_datetime(df["Peildatum"], format="%d-%m-%Y")
            df = df.set_index("Peildatum")
            gws = (df["Stand (cm t.o.v NAP)"].dropna() / 100.0)
            naam = csv.stem
            gws.name = naam
            # Sla over als al bestaat
            if naam not in pstore.oseries.index.tolist():
                pstore.add_oseries(gws, naam, metadata={
                    "x": 20000.0, "y": 390000.0,
                })
                print(f"  [OK] {naam}: {len(gws)} metingen")
            else:
                print(f"  [AL] {naam}: al in store")
        except Exception as e:
            print(f"  [FOUT] {csv.name}: {e}")

    # ── KNMI neerslag en verdamping ───────────────────────────
    print("\nKNMI data inladen...")
    for csv in sorted(KNMI_DIR.glob("neerslag_*.csv")):
        try:
            s = pd.read_csv(csv, index_col="Datum", parse_dates=True).iloc[:, 0]
            s.name = "Neerslag_KNMI"
            if s.name not in pstore.stresses.index.tolist():
                pstore.add_stress(s, s.name, kind="prec",
                                  metadata={"x": 20000.0, "y": 390000.0})
                print(f"  [OK] Neerslag: {len(s)} dagwaarden")
            else:
                print(f"  [AL] Neerslag: al in store")
        except Exception as e:
            print(f"  [FOUT] neerslag: {e}")

    for csv in sorted(KNMI_DIR.glob("verdamping_*.csv")):
        try:
            s = pd.read_csv(csv, index_col="Datum", parse_dates=True).iloc[:, 0]
            s.name = "Verdamping_KNMI"
            if s.name not in pstore.stresses.index.tolist():
                pstore.add_stress(s, s.name, kind="evap",
                                  metadata={"x": 20000.0, "y": 390000.0})
                print(f"  [OK] Verdamping: {len(s)} dagwaarden")
            else:
                print(f"  [AL] Verdamping: al in store")
        except Exception as e:
            print(f"  [FOUT] verdamping: {e}")

    print()
    print(f"Klaar! Store: {STORE_PAD}")
    print(f"  Tijdreeksen : {list(pstore.oseries.index)}")
    print(f"  Stressoren  : {list(pstore.stresses.index)}")
    print()
    print("Start dashboard:")
    print("  conda activate pastasdash")
    print("  pastasdash")
    print("Open: http://127.0.0.1:8050")


# Windows multiprocessing vereist deze guard
if __name__ == "__main__":
    maak_store()
