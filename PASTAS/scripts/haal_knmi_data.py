"""
haal_knmi_data.py
=================
Haalt dagelijkse neerslag- en verdampingsgegevens op van het KNMI
voor het dichtstbijzijnde station bij peilbuis B42C0133 (Zeeland).

Peilbuis locatie: 3.537°E, 51.578°N
Dichtstbijzijnde KNMI station: Axel (nr. 745) / Terneuzen (nr. 742)

Uitvoer:
  - data/knmi/neerslag_knmi_axel.csv
  - data/knmi/verdamping_knmi_axel.csv

Gebruik:
  python scripts/haal_knmi_data.py
"""

import os
import urllib.request
import io
import pandas as pd
from pathlib import Path

# ──────────────────────────────────────────────────────────────────
# Configuratie
# ──────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "knmi"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Station keuze:
# 742 = Terneuzen  (klimaatstation, heeft EV24/verdamping)
# 745 = Axel       (neerslagstation, alleen RD)
# We gebruiken 742 voor volledigheid (neerslag + verdamping)
STATION_ID = "742"
START_DATUM = "19950101"   # begin peilbuisreeks
EIND_DATUM  = "20041231"   # eind peilbuisreeks

# KNMI dagwaarden API endpoint
# Documentatie: https://daggegevens.knmi.nl/klimatologie/daggegevens
KNMI_URL = (
    "https://daggegevens.knmi.nl/klimatologie/daggegevens"
    "?stns={stn}&vars={var}&start={start}&end={end}"
)

# ──────────────────────────────────────────────────────────────────
# Hulpfunctie: KNMI CSV ophalen en parsen
# ──────────────────────────────────────────────────────────────────
def haal_knmi_dagwaarden(station: str, variabelen: str, start: str, eind: str) -> pd.DataFrame:
    """
    Haalt dagwaarden op van de KNMI API en geeft een pandas DataFrame terug.

    Parameters
    ----------
    station     : station ID als string, bijv. "742"
    variabelen  : komma-gescheiden variabelenamen, bijv. "RD,EV24"
    start       : startdatum YYYYMMDD
    eind        : einddatum YYYYMMDD

    Returns
    -------
    pd.DataFrame met DatetimeIndex en kolommen per variabele (SI-eenheden)
    """
    url = KNMI_URL.format(stn=station, var=variabelen, start=start, end=eind)
    print(f"Ophalen van: {url}")

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            inhoud = response.read().decode("utf-8")
    except Exception as e:
        raise ConnectionError(f"Kon KNMI-data niet ophalen: {e}")

    # KNMI CSV heeft commentaarregels die beginnen met '#'
    # Zoek de eerste regel die geen '#' heeft: dat is de header
    regels = inhoud.splitlines()
    data_start = 0
    for i, regel in enumerate(regels):
        if not regel.startswith("#") and regel.strip():
            data_start = i
            break

    # Verwijder spaties in kolomnamen
    df = pd.read_csv(
        io.StringIO("\n".join(regels[data_start:])),
        skipinitialspace=True
    )
    df.columns = df.columns.str.strip()

    # Datum kolom omzetten naar datetime index
    df["YYYYMMDD"] = pd.to_datetime(df["YYYYMMDD"].astype(str), format="%Y%m%d")
    df = df.set_index("YYYYMMDD")
    df.index.name = "Datum"

    return df


# ──────────────────────────────────────────────────────────────────
# Neerslag ophalen (RD: dagelijks, in 0.1 mm → omzetten naar mm)
# ──────────────────────────────────────────────────────────────────
def verwerk_neerslag(df: pd.DataFrame) -> pd.Series:
    """Extraheert de neerslaggereeks (RD) en converteert naar mm/dag."""
    if "RD" not in df.columns:
        raise ValueError("Kolom 'RD' niet gevonden in KNMI data.")
    neerslag = df["RD"].copy()
    # RD is in 0.1 mm, -1 = ontbrekend
    neerslag = neerslag.replace(-1, float("nan"))
    neerslag = neerslag / 10.0   # → mm/dag
    neerslag.name = "Neerslag_mm"
    return neerslag


# ──────────────────────────────────────────────────────────────────
# Verdamping ophalen (EV24: Makkink referentiegewasverdamping, 0.1 mm)
# ──────────────────────────────────────────────────────────────────
def verwerk_verdamping(df: pd.DataFrame) -> pd.Series:
    """Extraheert de verdampingsreeks (EV24) en converteert naar mm/dag."""
    if "EV24" not in df.columns:
        raise ValueError("Kolom 'EV24' niet gevonden in KNMI data.")
    verdamping = df["EV24"].copy()
    verdamping = verdamping.replace(-1, float("nan"))
    verdamping = verdamping / 10.0   # → mm/dag
    verdamping.name = "Verdamping_mm"
    return verdamping


# ──────────────────────────────────────────────────────────────────
# Hoofdprogramma
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("KNMI Data Ophalen voor Peilbuis B42C0133 (Zeeland)")
    print(f"Station: {STATION_ID} (Terneuzen)")
    print(f"Periode: {START_DATUM} t/m {EIND_DATUM}")
    print("=" * 60)

    # Haal neerslag + verdamping in één request op
    try:
        df_raw = haal_knmi_dagwaarden(
            station=STATION_ID,
            variabelen="RD,EV24",
            start=START_DATUM,
            eind=EIND_DATUM
        )
        print(f"\nRuwe data opgehaald: {len(df_raw)} rijen, kolommen: {list(df_raw.columns)}")

        # Verwerk neerslag
        neerslag = verwerk_neerslag(df_raw)
        neerslag_pad = OUTPUT_DIR / "neerslag_knmi_terneuzen.csv"
        neerslag.to_csv(neerslag_pad, sep=",", header=True)
        print(f"\n✓ Neerslag opgeslagen: {neerslag_pad}")
        print(f"  Perioden: {neerslag.index.min().date()} → {neerslag.index.max().date()}")
        print(f"  Gemiddelde: {neerslag.mean():.2f} mm/dag")

        # Verwerk verdamping
        verdamping = verwerk_verdamping(df_raw)
        verdamping_pad = OUTPUT_DIR / "verdamping_knmi_terneuzen.csv"
        verdamping.to_csv(verdamping_pad, sep=",", header=True)
        print(f"\n✓ Verdamping opgeslagen: {verdamping_pad}")
        print(f"  Gemiddelde: {verdamping.mean():.2f} mm/dag")

        print("\n✓ Klaar! KNMI data beschikbaar voor PASTAS modellering.")

    except (ConnectionError, ValueError) as e:
        print(f"\n⚠ Fout bij ophalen KNMI data: {e}")
        print("\nAlternatief: gebruik de dummy data functie in de notebook.")
