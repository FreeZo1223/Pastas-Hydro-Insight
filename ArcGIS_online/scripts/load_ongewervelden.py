"""
load_ongewervelden.py — Ongewervelden laden in DuckDB
======================================================

Laadt Ongewervelden data uit meerdere bronnen en schrijft naar DuckDB.

Bronvolgorde (deduplicatie op GlobalID):
  1. AGOL actueel  (FeatureServer/17, ~85 records, MET Soort)
  2. AGOL histoire (FeatureServer/64, ~1517 records, GEEN Soort — structureel)
  3. Backup 2022   (JSON, 463 records, MET Soort — aparte service)
  4. Backup 2021   (JSON, 14 records, NedNaam → soort)
  Fallbacks indien AGOL onbereikbaar:
  5. Backup 2024   (JSON, 66 records) vervangt stap 1
  6. Backup voor_2024 (JSON, 1317 records) vervangt stap 2

Bekende beperking:
  De voor_2024 / AGOL histoire laag heeft structureel geen Soort-veld.
  Records uit deze laag krijgen soort=NULL.

Gebruik:
    python scripts/load_ongewervelden.py
    python scripts/load_ongewervelden.py --alleen-backups   # skip AGOL
    python scripts/load_ongewervelden.py --droog-draaien    # geen DuckDB schrijven
"""

import os
import sys
import json
import time
import argparse
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Zorg voor UTF-8 output op Windows (voorkomt UnicodeEncodeError)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
import duckdb
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# PADEN
# ─────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

load_dotenv(PROJECT_DIR / ".env")

DUCKDB_PAD  = PROJECT_DIR / "Databeheer" / "00_kern" / "ewaarnemingen.duckdb"
BACKUP_DIR  = PROJECT_DIR / "archive" / "Backups"

BACKUP_PADEN = {
    "2022":     BACKUP_DIR / "Ongewervelden_2022_a35d3e1e5884456a88f17bf5da68476e" / "0_Ongewervelden_2022_data.json",
    "2021":     BACKUP_DIR / "Ongewervelden_2021_38641d7912a14c449e916f2b35026f0d" / "0_Ongewervelden_2021_data.json",
    "voor_2024":BACKUP_DIR / "Ongewervelden_voor_2024_6fa5d92c0c6f4cf49c7d2fd00c6d24ac" / "64_Ongewervelden_voor_2024_data.json",
    "2024":     BACKUP_DIR / "Ongewervelden_2024_8e3be03932c04413993d17c671000456" / "17_Ongewervelden_2024_data.json",
}

AGOL_URLS = {
    "actueel":  "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Ongewervelden_2024/FeatureServer/17",
    "histoire": "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Ongewervelden_voor_2024/FeatureServer/64",
}

AGOL_USERNAME = os.getenv("AGOL_USERNAME", "")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD", "")

BATCH_GROOTTE = 1000
MAX_RETRIES   = 5
TIMEOUT       = 60


# ─────────────────────────────────────────────
# AUTHENTICATIE
# ─────────────────────────────────────────────

def get_token() -> str | None:
    import requests
    if not AGOL_USERNAME or not AGOL_PASSWORD:
        print("⚠️  Geen AGOL credentials in .env — skip AGOL")
        return None
    try:
        print(f"🔐 Inloggen als '{AGOL_USERNAME}' ...")
        resp = requests.post(
            "https://www.arcgis.com/sharing/rest/generateToken",
            data={
                "username":   AGOL_USERNAME,
                "password":   AGOL_PASSWORD,
                "referer":    "https://www.arcgis.com",
                "expiration": 120,
                "f":          "json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        print("✅ Token verkregen.")
        return data["token"]
    except Exception as e:
        print(f"❌ Login mislukt: {e}")
        return None


# ─────────────────────────────────────────────
# AGOL PAGINERING
# ─────────────────────────────────────────────

def haal_agol_laag_op(url: str, token: str, laagnaam: str) -> pd.DataFrame | None:
    """Haal alle records op van een AGOL laag via paginering (GeoJSON, WGS84)."""
    import requests

    alle_records = []
    offset = 0

    print(f"  📡 {laagnaam}: ophalen van AGOL ...")

    while True:
        params = {
            "where":             "1=1",
            "outFields":         "*",
            "returnGeometry":    "true",
            "outSR":             "4326",
            "geometryPrecision": 6,
            "resultOffset":      offset,
            "resultRecordCount": BATCH_GROOTTE,
            "f":                 "geojson",
            "token":             token,
        }

        for poging in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(f"{url}/query", params=params, timeout=TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if poging == MAX_RETRIES:
                    print(f"\n  ❌ {laagnaam}: ophalen mislukt na {MAX_RETRIES} pogingen: {e}")
                    return None
                wacht = 2 ** poging
                print(f"  ⚠️  Poging {poging} mislukt, wacht {wacht}s ...", end="")
                time.sleep(wacht)
                print(" opnieuw.")

        features = data.get("features", [])
        if not features:
            break

        for feat in features:
            attrs = feat.get("properties") or feat.get("attributes") or {}
            geom  = feat.get("geometry")
            if geom:
                attrs["_geojson"] = json.dumps(geom)
            alle_records.append(attrs)

        offset += len(features)
        print(f"    {offset} records ...", end="\r")

        if not data.get("properties", {}).get("exceededTransferLimit", False) and len(features) < BATCH_GROOTTE:
            break

    print(f"  ✅ {laagnaam}: {len(alle_records)} records opgehaald via AGOL")
    return pd.DataFrame(alle_records) if alle_records else pd.DataFrame()


# ─────────────────────────────────────────────
# ESRI JSON BACKUP LEZEN
# ─────────────────────────────────────────────

def lees_esri_json_backup(pad: Path, laagnaam: str) -> pd.DataFrame:
    """Lees een ESRI JSON backup file naar een DataFrame."""
    print(f"  📂 {laagnaam}: lezen uit {pad.name} ...")
    with open(pad, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not features:
        print(f"  ⚠️  {laagnaam}: geen features gevonden in backup")
        return pd.DataFrame()

    records = []
    for feat in features:
        attrs = dict(feat.get("attributes", {}))
        geom  = feat.get("geometry")
        if geom:
            attrs["_geom_rd"] = geom  # RD New, herprojecteren later
        records.append(attrs)

    df = pd.DataFrame(records)
    print(f"  ✅ {laagnaam}: {len(df)} records gelezen uit backup")
    return df


# ─────────────────────────────────────────────
# GEOMETRY REPROJECTION (RD New → WGS84)
# ─────────────────────────────────────────────

def reproject_rd_naar_wgs84(df: pd.DataFrame) -> pd.DataFrame:
    """Converteer _geom_rd (RD New dict met x/y) naar GeoJSON WGS84 string in _geojson."""
    try:
        from pyproj import Transformer
    except ImportError:
        print("  ❌ pyproj niet geïnstalleerd. Installeer met: pip install pyproj")
        df["_geojson"] = None
        return df

    transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)

    geojson_list = []
    for geom in df.get("_geom_rd", [None] * len(df)):
        if geom and isinstance(geom, dict) and "x" in geom and "y" in geom:
            try:
                lon, lat = transformer.transform(float(geom["x"]), float(geom["y"]))
                geojson_list.append(json.dumps({"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}))
            except Exception:
                geojson_list.append(None)
        else:
            geojson_list.append(None)

    df["_geojson"] = geojson_list
    return df


# ─────────────────────────────────────────────
# DATUM PARSING
# ─────────────────────────────────────────────

def ms_naar_timestamp(val) -> datetime | None:
    """Converteer milliseconden-epoch naar datetime."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        ts = int(val)
        if ts == 0:
            return None
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def bepaal_datum_beste(rij: pd.Series) -> tuple:
    """Bepaal beste datum met prioriteit: invoerdatum_def > datum > creation_date > ingevoerd_datum."""
    for veld, label in [
        ("invoerdatum_def", "invoerdatum_def"),
        ("datum",           "datum"),
        ("creation_date",   "creation_date"),
        ("ingevoerd_datum", "ingevoerd_datum"),
    ]:
        val = rij.get(veld)
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            dt = ms_naar_timestamp(val) if isinstance(val, (int, float)) else val
            if dt is not None:
                # Unix timestamp als integer
                try:
                    ts = int(dt.timestamp())
                    return ts, label
                except Exception:
                    pass
    return None, "onbekend"


# ─────────────────────────────────────────────
# SCHEMA NORMALISATIE
# ─────────────────────────────────────────────

def normaliseer_schema(df: pd.DataFrame, bron_laag: str, bron_type: str) -> pd.DataFrame:
    """
    Hernoem AGOL/JSON velden naar canonical lowercase schema.
    Voegt ontbrekende kolommen toe als NULL.
    """
    # Veldmapping: AGOL/JSON naam → canonical
    mapping = {
        "GlobalID":         "global_id",
        "OBJECTID":         "object_id",
        "Soort":            "soort",
        "NedNaam":          "soort",         # 2021 backup
        "Aantal":           "aantal",
        "Gedrag":           "gedrag",
        "Levensstadium":    "stadium",        # 2022/2024/actueel
        "Stadium":          "stadium",        # voor_2024
        "Geslacht":         "geslacht",
        "Methode":          "methode",
        "Telmethode":       "telmethode",
        "Opmerking":        "opmerking",
        "Opmerkingen":      "opmerking",
        "Kleed":            "kleed",
        "Richting":         "richting",
        "Waarnemer":        "waarnemer",
        "Datum":            "datum",
        "CreationDate":     "creation_date",
        "EditDate":         "edit_date",
        "Creator":          "creator",
        "Editor":           "editor",
        "Ingevoerd_datum":  "ingevoerd_datum",
        "Ingevoerd_door":   "ingevoerd_door",
        "Invoerdatum_Def":  "invoerdatum_def",
        "_geojson":         "geometry",
        # Activiteit (2021) bewaren
        "Activiteit":       "gedrag",         # 2021 gebruikt Activiteit ipv Gedrag
    }

    # Hernoem aanwezige kolommen
    hernoem = {k: v for k, v in mapping.items() if k in df.columns and k != v}
    df = df.rename(columns=hernoem)

    # Verwijder AGOL-intern velden
    verwijder = {"_geom_rd", "SHAPE", "OBJECTID_y", "Shape__Area", "Shape__Length"}
    df = df.drop(columns=[c for c in verwijder if c in df.columns])

    # Vaste kolommen
    df["soortgroep"] = "Ongewervelden"
    df["_bron_laag"] = bron_laag
    df["_bron_type"] = bron_type

    # Zorg dat canonical kolommen bestaan (NULL als niet aanwezig)
    verplicht = [
        "global_id", "object_id", "soort", "aantal", "gedrag", "stadium",
        "geslacht", "methode", "telmethode", "opmerking", "kleed", "richting",
        "waarnemer", "datum", "creation_date", "edit_date", "creator", "editor",
        "ingevoerd_datum", "ingevoerd_door", "invoerdatum_def", "geometry",
    ]
    for kol in verplicht:
        if kol not in df.columns:
            df[kol] = None

    # Normaliseer GlobalID: verwijder {} indien aanwezig
    if "global_id" in df.columns:
        df["global_id"] = df["global_id"].astype(str).str.strip("{}").str.upper()
        df["global_id"] = df["global_id"].replace("NAN", None)
        df["global_id"] = df["global_id"].replace("NONE", None)

    return df


# ─────────────────────────────────────────────
# DATUM KOLOMMEN NORMALISEREN
# ─────────────────────────────────────────────

def normaliseer_datums(df: pd.DataFrame) -> pd.DataFrame:
    """Converteer timestamp-kolommen van ms-epoch naar Python datetime."""
    datum_kolommen = ["datum", "creation_date", "edit_date", "ingevoerd_datum", "invoerdatum_def"]
    for kol in datum_kolommen:
        if kol in df.columns:
            df[kol] = df[kol].apply(
                lambda v: ms_naar_timestamp(v) if isinstance(v, (int, float)) else v
            )
    return df


# ─────────────────────────────────────────────
# HOOFDPROGRAMMA
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Laad Ongewervelden data in DuckDB")
    parser.add_argument("--alleen-backups", action="store_true",
                        help="Sla AGOL over, gebruik alleen JSON backups")
    parser.add_argument("--droog-draaien",  action="store_true",
                        help="Verwerk data maar schrijf NIET naar DuckDB")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  Ongewervelden → DuckDB")
    print("="*60)
    print(f"  Gestart: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  DuckDB:  {DUCKDB_PAD}")
    print()

    bronnen = []   # list of (df, prioriteit) — lagere waarde = hogere prioriteit

    # ── Stap 1 & 2: AGOL (actueel + histoire) ──────────────────
    token = None
    if not args.alleen_backups:
        token = get_token()

    if token:
        # Actueel (FeatureServer/17) — MET Soort
        df_act = haal_agol_laag_op(AGOL_URLS["actueel"], token, "Ongewervelden_actueel")
        if df_act is not None and len(df_act) > 0:
            df_act = normaliseer_schema(df_act, "Ongewervelden_2024", "agol_actueel")
            df_act = normaliseer_datums(df_act)
            bronnen.append((df_act, 1))
            print(f"  → actueel: {len(df_act)} records")
        else:
            print("  ⚠️  AGOL actueel leeg of mislukt — gebruik backup 2024 als fallback")
            df_fb = lees_esri_json_backup(BACKUP_PADEN["2024"], "Backup_2024")
            df_fb = reproject_rd_naar_wgs84(df_fb)
            df_fb = normaliseer_schema(df_fb, "Ongewervelden_2024", "agol_actueel")
            df_fb = normaliseer_datums(df_fb)
            if len(df_fb) > 0:
                bronnen.append((df_fb, 1))

        # Histoire (FeatureServer/64) — GEEN Soort (structureel)
        df_hist = haal_agol_laag_op(AGOL_URLS["histoire"], token, "Ongewervelden_histoire")
        if df_hist is not None and len(df_hist) > 0:
            df_hist = normaliseer_schema(df_hist, "Ongewervelden_voor_2024", "agol_historie")
            df_hist = normaliseer_datums(df_hist)
            bronnen.append((df_hist, 2))
            print(f"  → histoire: {len(df_hist)} records")
        else:
            print("  ⚠️  AGOL histoire leeg of mislukt — gebruik backup voor_2024 als fallback")
            df_fb2 = lees_esri_json_backup(BACKUP_PADEN["voor_2024"], "Backup_voor_2024")
            df_fb2 = reproject_rd_naar_wgs84(df_fb2)
            df_fb2 = normaliseer_schema(df_fb2, "Ongewervelden_voor_2024", "agol_historie")
            df_fb2 = normaliseer_datums(df_fb2)
            if len(df_fb2) > 0:
                bronnen.append((df_fb2, 2))
    else:
        print("  ℹ️  Geen AGOL token — gebruik JSON backups als primaire bron")
        for naam, prioriteit, bron_laag, bron_type in [
            ("voor_2024", 2, "Ongewervelden_voor_2024", "agol_historie"),
            ("2024",      1, "Ongewervelden_2024",      "agol_actueel"),
        ]:
            df_fb = lees_esri_json_backup(BACKUP_PADEN[naam], f"Backup_{naam}")
            df_fb = reproject_rd_naar_wgs84(df_fb)
            df_fb = normaliseer_schema(df_fb, bron_laag, bron_type)
            df_fb = normaliseer_datums(df_fb)
            if len(df_fb) > 0:
                bronnen.append((df_fb, prioriteit))

    # ── Stap 3: Backup 2022 (aparte service, MET Soort) ────────
    df_2022 = lees_esri_json_backup(BACKUP_PADEN["2022"], "Backup_2022")
    df_2022 = reproject_rd_naar_wgs84(df_2022)
    df_2022 = normaliseer_schema(df_2022, "Ongewervelden_2022", "agol_historie")
    df_2022 = normaliseer_datums(df_2022)
    if len(df_2022) > 0:
        bronnen.append((df_2022, 3))

    # ── Stap 4: Backup 2021 (NedNaam → soort) ──────────────────
    df_2021 = lees_esri_json_backup(BACKUP_PADEN["2021"], "Backup_2021")
    df_2021 = reproject_rd_naar_wgs84(df_2021)
    df_2021 = normaliseer_schema(df_2021, "Ongewervelden_2021", "agol_historie")
    df_2021 = normaliseer_datums(df_2021)
    if len(df_2021) > 0:
        bronnen.append((df_2021, 4))

    if not bronnen:
        print("\n❌ Geen bronnen beschikbaar. Script gestopt.")
        sys.exit(1)

    # ── Stap 5: Merge en deduplicatie ──────────────────────────
    print("\n  🔀 Samenvoegen en dedupliceren ...")

    # Sorteer op prioriteit (laagste = hoogste prioriteit → keep="first")
    bronnen.sort(key=lambda x: x[1])

    # Voeg samen met prioriteitskolom voor debugging
    alle_dfs = []
    for df, prio in bronnen:
        df = df.copy()
        df["_prio"] = prio
        alle_dfs.append(df)

    # Gemeenschappelijke kolommen (union schema)
    alle_kolommen = set()
    for df in alle_dfs:
        alle_kolommen.update(df.columns)
    for df in alle_dfs:
        for kol in alle_kolommen - set(df.columns):
            df[kol] = None

    merged = pd.concat(alle_dfs, ignore_index=True)

    # Dedupliceer op global_id
    voor_dedup = len(merged)
    merged_geldig = merged[merged["global_id"].notna() & (merged["global_id"] != "")]
    merged_geen_id = merged[merged["global_id"].isna() | (merged["global_id"] == "")]

    merged_geldig = merged_geldig.sort_values("_prio").drop_duplicates(
        subset="global_id", keep="first"
    )
    merged = pd.concat([merged_geldig, merged_geen_id], ignore_index=True)
    na_dedup = len(merged)
    print(f"  → {voor_dedup} records → {na_dedup} na deduplicatie op GlobalID ({voor_dedup - na_dedup} duplicaten verwijderd)")

    # ── Soort-verrijking: vul lege soort in via GlobalID-koppeling ──
    if "soort" in merged.columns and len(df_2022) > 0:
        soort_lookup = dict(zip(df_2022["global_id"], df_2022["soort"]))
        gevuld_voor = merged["soort"].notna().sum()
        merged["soort"] = merged.apply(
            lambda r: soort_lookup.get(r["global_id"], r["soort"])
            if pd.isna(r.get("soort")) else r["soort"],
            axis=1
        )
        gevuld_na = merged["soort"].notna().sum()
        extra = gevuld_na - gevuld_voor
        if extra > 0:
            print(f"  🔗 Soort-verrijking via 2022-koppeling: +{extra} records aangevuld")

    # ── Stap 6: datum_beste berekenen ──────────────────────────
    print("  📅 Datum_beste berekenen ...")
    datum_resultaten = merged.apply(bepaal_datum_beste, axis=1)
    merged["datum_beste"] = [r[0] for r in datum_resultaten]
    merged["datum_bron"]  = [r[1] for r in datum_resultaten]

    # Verwijder hulpkolom
    merged = merged.drop(columns=["_prio"], errors="ignore")

    # ── Stap 7: Eindschema opschonen ───────────────────────────
    # Zorg voor correcte kolomvolgorde
    volgorde = [
        "global_id", "object_id", "soortgroep", "_bron_laag", "_bron_type",
        "soort", "aantal", "gedrag", "stadium", "geslacht", "methode",
        "telmethode", "opmerking", "kleed", "richting", "waarnemer",
        "datum", "creation_date", "edit_date", "ingevoerd_datum",
        "ingevoerd_door", "invoerdatum_def", "datum_beste", "datum_bron",
        "geometry",
    ]
    # Voeg ontbrekende kolommen toe
    for kol in volgorde:
        if kol not in merged.columns:
            merged[kol] = None
    # Overige kolommen achteraan
    extra_kolommen = [c for c in merged.columns if c not in volgorde]
    merged = merged[volgorde + extra_kolommen]

    # ── Rapportage ─────────────────────────────────────────────
    print("\n" + "─"*50)
    print("  RESULTAAT:")
    print(f"  Totaal records:     {len(merged)}")

    soort_pct = merged["soort"].notna().mean() * 100
    print(f"  Soort gevuld:       {merged['soort'].notna().sum()} ({soort_pct:.1f}%)")

    datum_pct = (merged["datum_beste"].notna()).mean() * 100
    print(f"  Datum_beste gevuld: {merged['datum_beste'].notna().sum()} ({datum_pct:.1f}%)")

    geom_pct = merged["geometry"].notna().mean() * 100
    print(f"  Geometry gevuld:    {merged['geometry'].notna().sum()} ({geom_pct:.1f}%)")

    print("\n  Per bron:")
    for (bron_laag, bron_type), grp in merged.groupby(["_bron_laag", "_bron_type"]):
        soort_n = grp["soort"].notna().sum()
        print(f"    {bron_type:15s} {bron_laag:35s}  {len(grp):5d} records  soort: {soort_n}")

    print("\n  Datum_bron verdeling:")
    for bron, n in merged["datum_bron"].value_counts().items():
        print(f"    {bron:20s}: {n}")
    print("─"*50)

    if args.droog_draaien:
        print("\n  ⚠️  Droog-draaien modus: GEEN schrijven naar DuckDB")
        print("  Script klaar.")
        return

    # ── Stap 8: Schrijven naar DuckDB ──────────────────────────
    print(f"\n  💾 Schrijven naar DuckDB ...")
    print(f"     {DUCKDB_PAD}")

    con = duckdb.connect(str(DUCKDB_PAD))
    try:
        # Drop bestaande tabel (was leeg en met verkeerd schema)
        con.execute("DROP TABLE IF EXISTS waarnemingen_ongewervelden")

        # Registreer DataFrame en maak tabel aan
        con.register("_ongewervelden_df", merged)
        con.execute("CREATE TABLE waarnemingen_ongewervelden AS SELECT * FROM _ongewervelden_df")
        con.unregister("_ongewervelden_df")

        # Indices
        con.execute("CREATE INDEX idx_ongewervelden_global_id ON waarnemingen_ongewervelden(global_id)")
        con.execute("CREATE INDEX idx_ongewervelden_datum_beste ON waarnemingen_ongewervelden(datum_beste)")

        # Verificatie
        telling = con.execute("SELECT COUNT(*) FROM waarnemingen_ongewervelden").fetchone()[0]
        if telling != len(merged):
            raise ValueError(f"Schrijffout: {telling} rijen in DuckDB maar {len(merged)} verwacht!")

        # Pipeline log bijwerken
        try:
            con.execute("""
                INSERT INTO _pipeline_log (run_datum, laagnaam, nieuw, bijgewerkt, ongewijzigd, fouten, tijdstip)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [datetime.now().date(), "waarnemingen_ongewervelden",
                  telling, 0, 0, 0, datetime.now()])
        except Exception as log_e:
            print(f"  ⚠️  Pipeline log bijwerken mislukt (niet kritiek): {log_e}")

        print(f"\n  ✅ {telling} records geschreven naar waarnemingen_ongewervelden")
        print(f"     Indices aangemaakt op global_id en datum_beste")

    finally:
        con.close()

    print("\n  🎉 Klaar!\n")


if __name__ == "__main__":
    main()
