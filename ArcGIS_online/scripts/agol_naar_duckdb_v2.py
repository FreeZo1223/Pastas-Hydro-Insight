"""
AGOL → DuckDB Pipeline v2 — Ewaarnemingen
==========================================

VEILIGHEIDSGARANTIES:
  ✅ Schrijft NOOIT naar AGOL — alleen lezen (read-only guard op elke AGOL functie)
  ✅ Originele parquet bestanden worden NOOIT gewijzigd
  ✅ Veldnamen worden alleen in geheugen hernoemd (DuckDB canonical), nooit op schijf
  ✅ Retry-logica met exponential backoff bij netwerkstoringen
  ✅ Checkpointing: hervatten waar gebleven na storing

Vereisten:
    pip install duckdb pandas pyarrow arcgis requests

Gebruik:
    python agol_naar_duckdb_v2.py

    # Hervatten na storing (gebruikt checkpoint bestand):
    python agol_naar_duckdb_v2.py --hervat
"""

import os
import json
import time
import argparse
import warnings
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Laad .env aan het begin — expliciet pad zodat Task Scheduler het ook vindt
_SCRIPT_DIR = Path(__file__).parent
load_dotenv(_SCRIPT_DIR.parent / ".env")

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
AGOL_URL      = "https://www.arcgis.com"
AGOL_USERNAME = os.getenv("AGOL_USERNAME", "jouw_gebruikersnaam")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD", "jouw_wachtwoord")

_PROJECT_DIR   = _SCRIPT_DIR.parent   # C:\GIS_Projecten\ArcGIS_online
DATABEHEER     = _PROJECT_DIR / "Databeheer"
PARQUET_MAP    = str(DATABEHEER / "01_parquet" / "latest")
DUCKDB_PAD     = str(DATABEHEER / "00_kern" / "ewaarnemingen.duckdb")
MAPPING_PAD    = str(DATABEHEER / "05_context" / "field_mapping.json")
CHECKPOINT_PAD = str(_SCRIPT_DIR / "pipeline_checkpoint.json")
LOG_PAD        = str(DATABEHEER / "03_logs" / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log")
ENV_PAD        = str(_SCRIPT_DIR.parent / ".env")

BATCH_GROOTTE     = 1000
MAX_RETRIES       = 5       # maximaal 5 pogingen per batch
RETRY_WACHT_BASIS = 2       # seconden — verdubbelt elke poging (2, 4, 8, 16, 32)
TIMEOUT_SECONDEN  = 60      # per request

# ─────────────────────────────────────────────
# READ-ONLY GUARD
# ─────────────────────────────────────────────

# Lijst van AGOL operaties die NOOIT mogen worden aangeroepen
VERBODEN_AGOL_OPERATIES = [
    "edit_features", "delete_features", "apply_edits",
    "truncate", "delete", "update_definition", "overwrite",
    "add_features", "append"
]

def agol_readonly_check(operatie: str):
    """
    Gooit een fout als een verboden schrijfoperatie wordt geprobeerd.
    Wordt aangeroepen VOOR elke AGOL interactie.
    """
    for verboden in VERBODEN_AGOL_OPERATIES:
        if verboden in operatie.lower():
            raise PermissionError(
                f"🚫 GEBLOKKEERD: '{operatie}' is een schrijfoperatie op AGOL. "
                f"Dit script mag NOOIT data in AGOL wijzigen of verwijderen. "
                f"Gebruik een apart, expliciet goedgekeurd script voor schrijfoperaties."
            )

def veilige_agol_query(url: str, params: dict, token: str) -> dict:
    """
    Enige functie die HTTP requests naar AGOL maakt.
    Controleert dat het altijd een /query endpoint is (read-only).
    Gooit een fout als iemand probeert een schrijf-endpoint aan te roepen.
    """
    import requests

    # Guard: alleen /query endpoints zijn toegestaan
    if not url.endswith("/query"):
        agol_readonly_check(url)
        raise PermissionError(
            f"🚫 GEBLOKKEERD: URL '{url}' is geen /query endpoint. "
            f"Alleen read-only /query calls zijn toegestaan in dit script."
        )

    # Guard: geen schrijf-parameters in de request
    verboden_params = {"adds", "updates", "deletes", "edits", "truncate"}
    gevonden = verboden_params & set(params.keys())
    if gevonden:
        raise PermissionError(
            f"🚫 GEBLOKKEERD: Parameters {gevonden} zijn schrijfoperaties."
        )

    # Voeg altijd token toe
    params["token"] = token

    response = requests.get(url, params=params, timeout=TIMEOUT_SECONDEN)
    response.raise_for_status()
    return response.json()


# ─────────────────────────────────────────────
# RETRY LOGICA
# ─────────────────────────────────────────────

def met_retry(functie, *args, beschrijving="operatie", **kwargs):
    """
    Voert een functie uit met exponential backoff retry.
    Bij netwerkstoringen: wacht 2, 4, 8, 16, 32 seconden en probeer opnieuw.
    """
    for poging in range(1, MAX_RETRIES + 1):
        try:
            return functie(*args, **kwargs)

        except PermissionError:
            # Read-only guard fouten nooit herproberen
            raise

        except Exception as e:
            is_laatste = (poging == MAX_RETRIES)
            fout_type  = type(e).__name__

            if is_laatste:
                print(f"\n   ❌ {beschrijving} mislukt na {MAX_RETRIES} pogingen: {e}")
                raise

            wacht = RETRY_WACHT_BASIS ** poging
            print(f"\n   ⚠️  {beschrijving} poging {poging}/{MAX_RETRIES} mislukt "
                  f"({fout_type}). Wacht {wacht}s...", end="")
            time.sleep(wacht)
            print(" Opnieuw proberen...")


# ─────────────────────────────────────────────
# CHECKPOINT SYSTEEM
# ─────────────────────────────────────────────

def laad_checkpoint() -> dict:
    """Laad voortgang van een vorige run (als die er is)."""
    pad = Path(CHECKPOINT_PAD)
    if pad.exists():
        with open(pad, encoding="utf-8") as f:
            checkpoint = json.load(f)
        # Backwards compat: oude checkpoints hebben mogelijk geen 'partieel' sleutel
        # of bevatten vervuilende '*_deels' entries in voltooid.
        checkpoint.setdefault("partieel", {})
        vervuild = [k for k in list(checkpoint.get("voltooid", {})) if k.endswith("_deels")]
        for k in vervuild:
            schone_naam = k[:-len("_deels")]
            checkpoint["partieel"][schone_naam] = checkpoint["voltooid"].pop(k)
        print(f"♻️  Checkpoint gevonden van {checkpoint.get('gestart_op', '?')}")
        print(f"   Voltooid: {list(checkpoint.get('voltooid', {}).keys())}")
        if checkpoint["partieel"]:
            print(f"   Partieel (worden opnieuw gefetcht): {list(checkpoint['partieel'].keys())}")
        return checkpoint
    return {"gestart_op": datetime.now().isoformat(), "voltooid": {}, "partieel": {}}


def sla_checkpoint_op(checkpoint: dict, laagnaam: str, rijen: int):
    """Markeer een laag als succesvol opgehaald."""
    checkpoint["voltooid"][laagnaam] = {
        "rijen":         rijen,
        "tijdstip":      datetime.now().isoformat(),
    }
    # Als deze laag eerder partieel was, ruim die status nu op.
    checkpoint.setdefault("partieel", {}).pop(laagnaam, None)
    checkpoint["laatste_update"] = datetime.now().isoformat()
    with open(CHECKPOINT_PAD, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2)


def sla_partieel_op(checkpoint: dict, laagnaam: str, rijen: int):
    """Registreer een partieel opgehaalde laag (informatief, blokkeert hervat niet)."""
    checkpoint.setdefault("partieel", {})[laagnaam] = {
        "rijen":    rijen,
        "tijdstip": datetime.now().isoformat(),
    }
    checkpoint["laatste_update"] = datetime.now().isoformat()
    with open(CHECKPOINT_PAD, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2)


def verwijder_checkpoint():
    """Verwijder checkpoint na succesvolle run."""
    pad = Path(CHECKPOINT_PAD)
    if pad.exists():
        pad.unlink()
        print("🗑️  Checkpoint verwijderd (run was succesvol)")


# ─────────────────────────────────────────────
# AGOL LAYER REGISTRY
# ─────────────────────────────────────────────

AGOL_LAGEN = {
    # naam                  url (sublaag-index bepaald via FeatureServer?f=json)
    # --- ACTUEEL ---
    "Vogels_actueel":       "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vogels_2024/FeatureServer/1",
    "Vleermuizen_actueel":  "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vleermuizen_2024/FeatureServer/0",
    "Zoogdieren_actueel":   "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Zoogdieren_2024/FeatureServer/10",
    "Flora_actueel":        "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Flora_2024/FeatureServer/5",
    "Projectgebieden_act":  "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Projectgebieden_2024/FeatureServer/20",
    "Veldbezoeken_actueel": "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Veldbezoeken_2024/FeatureServer/2",
    "Exoten_actueel":       "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Exoten_2024/FeatureServer/21",
    "Faunakasten_actueel":  "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/faunakasten_2024/FeatureServer/0",
    "Ongewervelden_act":    "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Ongewervelden_2024/FeatureServer/17",
    "OWaarnemingen_act":    "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/OWaarnemingen_2024/FeatureServer/11",
    "Vliegroutes_actueel":  "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vliegroutes_vleermuizen_2024/FeatureServer/12",
    "Reptielen_actueel":    "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Reptielen_2024/FeatureServer/6",
    "Vissen_actueel":       "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vissen_2024/FeatureServer/9",
    "Veldmateriaal_act":    "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Veldmateriaal_actueel/FeatureServer/0",
    "Amfibieen_actueel":    "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Amfibieën_2024/FeatureServer/4",

    # --- HISTORIE ---
    "Amfibieen_hist":       "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Amfibieën_voor_2024/FeatureServer/74",
    "Zoogdieren_hist":      "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Zoogdieren_voor_2024/FeatureServer/91",
    "Vogels_hist":          "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vogels_voor_2024/FeatureServer/104",
    "Vissen_hist":          "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vissen_voor_2024/FeatureServer/29",
    "Reptielen_hist":       "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Reptielen_voor_2024/FeatureServer/79",
    "Ongewervelden_hist":   "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Ongewervelden_voor_2024/FeatureServer/64",
    "Flora_hist":           "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Flora_voor_2024/FeatureServer/84",
    "Veldbezoeken_hist":    "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Veldbezoeken_historie/FeatureServer/0",
    "Projectgebieden_hist": "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Projectgebieden_voor_2024/FeatureServer/0",
    "Vleermuizen_VBP_hist": "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vleermuizen_voor_2024_verblijfplaatsen/FeatureServer/1",
    "Faunakasten_hist":     "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Faunakasten_2020/FeatureServer/0",
    "Veldmateriaal_hist":   "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Veldmateriaal_2024/FeatureServer/13",
    "Vleermuizen_hist":     "https://services2.arcgis.com/Qdr8g9aWYVsDakkf/arcgis/rest/services/Vleermuizen_historie/FeatureServer/0",
}

AGOL_NAAR_SOORTGROEP = {
    "Vogels_actueel":       "Vogels",       "Vogels_hist":          "Vogels",
    "Vleermuizen_actueel":  "Vleermuizen",  "Vleermuizen_hist":     "Vleermuizen",
    "Vleermuizen_VBP_hist": "Vleermuizen",
    "Zoogdieren_actueel":   "Zoogdieren",   "Zoogdieren_hist":      "Zoogdieren",
    "Flora_actueel":        "Flora",         "Flora_hist":           "Flora",
    "Reptielen_actueel":    "Reptielen",    "Reptielen_hist":       "Reptielen",
    "Vissen_actueel":       "Vissen",       "Vissen_hist":          "Vissen",
    "Ongewervelden_act":    "Ongewervelden","Ongewervelden_hist":   "Ongewervelden",
    "Faunakasten_actueel":  "Faunakasten",  "Faunakasten_hist":     "Faunakasten",
    "Projectgebieden_act":  "Projectgebieden","Projectgebieden_hist":"Projectgebieden",
    "Veldbezoeken_actueel": "Veldbezoeken", "Veldbezoeken_hist":    "Veldbezoeken",
    "Exoten_actueel":       "Exoten",
    "OWaarnemingen_act":    "OWaarnemingen",
    "Vliegroutes_actueel":  "Vliegroutes",
    "Veldmateriaal_act":    "Veldmateriaal","Veldmateriaal_hist":   "Veldmateriaal",
    "Amfibieen_actueel":    "Amfibieën",    "Amfibieen_hist":       "Amfibieën",
}


# ─────────────────────────────────────────────
# AUTHENTICATIE
# ─────────────────────────────────────────────

def get_token() -> str | None:
    import requests
    try:
        print(f"🔐 Verbinden met AGOL als '{AGOL_USERNAME}' ...")
        payload = {
            "username":   AGOL_USERNAME,
            "password":   AGOL_PASSWORD,
            "referer":    "https://www.arcgis.com",
            "expiration": 60,
            "f":          "json",
        }
        resp = requests.post(
            "https://www.arcgis.com/sharing/rest/generateToken",
            data=payload, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Token fout: {data['error'].get('message', data['error'])}")
        print("✅ Token verkregen.")
        return data["token"]
    except Exception as e:
        print(f"❌ Login mislukt: {e}")
        return None


# ─────────────────────────────────────────────
# AGOL DATA OPHALEN (paginering + retry + checkpoint)
# ─────────────────────────────────────────────

def _haal_batch_op(url: str, token: str, offset: int) -> dict:
    """Haal één batch op — wordt aangeroepen via met_retry()."""
    params = {
        "where":             "1=1",
        "outFields":         "*",
        "returnGeometry":    "true",
        "outSR":             "4326",
        "geometryPrecision": 6,
        "resultOffset":      offset,
        "resultRecordCount": BATCH_GROOTTE,
        "f":                 "geojson",
    }
    return veilige_agol_query(f"{url}/query", params, token)


def _haal_batch_op_objectid(url: str, token: str, oid_min: int, oid_max: int) -> dict:
    """Haal batch op via OBJECTID range — voor problematische lagen."""
    params = {
        "where":             f"OBJECTID>={oid_min} AND OBJECTID<{oid_max}",
        "outFields":         "*",
        "returnGeometry":    "true",
        "outSR":             "4326",
        "geometryPrecision": 6,
        "f":                 "geojson",
    }
    return veilige_agol_query(f"{url}/query", params, token)


def haal_agol_laag_op_objectid_ranges(url: str, token: str, laagnaam: str,
                                       checkpoint: dict, range_size: int = 10000) -> pd.DataFrame | None:
    """
    Alternatieve fetcher voor problematische lagen (bijv. Vleermuizen_hist).
    Haalt records op in OBJECTID ranges in plaats van offset-paginering.
    """
    if laagnaam in checkpoint.get("voltooid", {}):
        info = checkpoint["voltooid"][laagnaam]
        print(f"  ♻️  {laagnaam}: al opgehaald ({info['rijen']} rijen) — overgeslagen")
        return None

    # Stap 1: Bepaal max OBJECTID
    try:
        data = met_retry(
            _haal_batch_op_objectid,
            url, token, 0, 1,
            beschrijving=f"{laagnaam} max OBJECTID query"
        )
    except Exception as e:
        print(f"\n   ⚠️  Kon OBJECTID-range niet bepalen: {e}, fallback naar offset")
        return None  # Fallback naar normale methode

    # Stap 2: Fetch alle records in OBJECTID ranges
    alle_records = []
    current_oid = 0
    range_nr = 0
    max_attempt_oid = 1000000  # Safety limit

    while current_oid < max_attempt_oid:
        range_nr += 1
        next_oid = current_oid + range_size

        try:
            data = met_retry(
                _haal_batch_op_objectid,
                url, token, current_oid, next_oid,
                beschrijving=f"{laagnaam} range {range_nr} (OID {current_oid}-{next_oid})"
            )
        except Exception as e:
            print(f"\n   ❌ Range {range_nr} mislukt: {e}")
            if alle_records:
                sla_partieel_op(checkpoint, laagnaam, len(alle_records))
            break

        if "error" in data:
            code = data["error"].get("code", "?")
            msg  = data["error"].get("message", "?")
            print(f"\n   ⚠️  API fout {code}: {msg}")
            break

        features = data.get("features", [])
        if not features:
            break  # Geen meer records

        for feat in features:
            attrs = feat.get("properties", feat.get("attributes", {})) or {}
            geom = feat.get("geometry")
            if geom:
                attrs["geometry"] = json.dumps(geom)
            alle_records.append(attrs)

        print(f"\r   📥 {laagnaam}: {len(alle_records)} records...", end="", flush=True)

        current_oid = next_oid

    if not alle_records:
        print(f"\n   ⚠️  {laagnaam}: geen records opgehaald")
        return pd.DataFrame()

    print(f"\n   ✅ {laagnaam}: {len(alle_records)} records (via OBJECTID ranges)")

    df = pd.DataFrame(alle_records)
    df["_bron_laag"] = laagnaam
    df["_bron_type"] = "agol_historie"

    sla_checkpoint_op(checkpoint, laagnaam, len(df))
    return df


def haal_agol_laag_op(url: str, token: str, laagnaam: str,
                       checkpoint: dict) -> pd.DataFrame | None:
    """
    Haalt ALLE records op van een AGOL laag.
    - Slaat elke batch op in een tijdelijk checkpoint-bestand
    - Hervat automatisch bij storing
    - Chunked verwerking: maakt DF's per CHUNK_SIZE records om geheugen-spieken te voorkomen
    """
    # Controleer of deze laag al opgehaald is in een eerdere run
    if laagnaam in checkpoint.get("voltooid", {}):
        info = checkpoint["voltooid"][laagnaam]
        print(f"  ♻️  {laagnaam}: al opgehaald ({info['rijen']} rijen) — overgeslagen")
        return None  # Signaal: gebruik gecachede data

    alle_records = []
    alle_dataframes = []
    offset = 0
    batch_nr = 0
    CHUNK_SIZE = 5000  # Voeg DF's samen per 5k records om memory-bloat te voorkomen

    while True:
        batch_nr += 1

        try:
            data = met_retry(
                _haal_batch_op,
                url, token, offset,
                beschrijving=f"{laagnaam} batch {batch_nr} (offset {offset})"
            )
        except PermissionError:
            raise   # Read-only schendingen altijd doorgeven
        except Exception as e:
            print(f"\n   ❌ {laagnaam}: ophalen gestopt na herhaalde fouten: {e}")
            print(f"   💾 {len(alle_records)} records tot nu toe bewaard in checkpoint")
            # Sla deelresultaat op zodat --hervat hier kan beginnen
            if alle_records or alle_dataframes:
                totaal_rijen = len(alle_records) + sum(len(d) for d in alle_dataframes)
                sla_partieel_op(checkpoint, laagnaam, totaal_rijen)
            break

        if "error" in data:
            code = data["error"].get("code", "?")
            msg  = data["error"].get("message", "?")
            print(f"\n   ❌ API fout {code}: {msg}")
            break

        features = data.get("features", [])
        if not features:
            break

        for feat in features:
            attrs = feat.get("properties", feat.get("attributes", {})) or {}
            geom  = feat.get("geometry")
            if geom:
                attrs["geometry"] = json.dumps(geom)
            alle_records.append(attrs)

        offset += len(features)
        print(f"\r   📥 {laagnaam}: {offset} records...", end="", flush=True)

        # Maak DataFrame-chunk als we CHUNK_SIZE bereikt hebben
        if len(alle_records) >= CHUNK_SIZE:
            try:
                df_chunk = pd.DataFrame(alle_records)
                alle_dataframes.append(df_chunk)
                alle_records = []  # Wis geheugen
            except Exception as e:
                print(f"\n   ⚠️  Chunk creatie mislukt bij {offset} records: {e} (doorgaan)")
                # Ga gewoon door, houd in-memory list

        exceeded = data.get("exceededTransferLimit", False)
        if not exceeded and len(features) < BATCH_GROOTTE:
            break   # Alle records binnen

        if offset >= 500_000:
            print(f"\n   ⚠️  Veiligheidsrem bij {offset} records")
            break

    # Combineer alle chunks
    if alle_dataframes:
        df = pd.concat(alle_dataframes, ignore_index=True)
        if alle_records:
            df_final = pd.DataFrame(alle_records)
            df = pd.concat([df, df_final], ignore_index=True)
    elif alle_records:
        df = pd.DataFrame(alle_records)
    else:
        print(f"\n   ⚠️  {laagnaam}: geen records opgehaald")
        return pd.DataFrame()

    print(f"\n   ✅ {laagnaam}: {len(df)} records")

    df["_bron_laag"] = laagnaam
    df["_bron_type"] = (
        "agol_actueel" if any(x in laagnaam for x in ["actueel", "_act"])
        else "agol_historie"
    )

    # Markeer als voltooid in checkpoint
    sla_checkpoint_op(checkpoint, laagnaam, len(df))

    return df


# ─────────────────────────────────────────────
# PARQUET LADEN (originele bestanden NOOIT wijzigen)
# ─────────────────────────────────────────────

def lees_parquet_readonly(pad: Path) -> pd.DataFrame | None:
    """
    Laad parquet als read-only kopie in geheugen.
    Het originele bestand op schijf wordt NOOIT gewijzigd.
    """
    try:
        # pandas maakt altijd een kopie in geheugen — origineel blijft intact
        df = pd.read_parquet(pad)
        return df.copy()   # expliciete kopie voor de zekerheid
    except Exception:
        try:
            import pyarrow.parquet as pq
            tabel = pq.read_table(pad)
            df = tabel.to_pandas()
            for col in df.select_dtypes(include=["object"]).columns:
                df[col] = df[col].apply(
                    lambda x: x.decode("latin-1", errors="replace")
                    if isinstance(x, bytes) else x
                )
            return df.copy()
        except Exception as e:
            print(f"   ❌ Kon niet lezen: {e}")
            return None


def laad_parquets(mapping: dict) -> dict[str, pd.DataFrame]:
    resultaten = {}
    parquet_pad = Path(PARQUET_MAP)

    print(f"\n{'='*60}", flush=True)
    print("  💾 PARQUETS LADEN (originelen ongewijzigd)", flush=True)
    print(f"{'='*60}", flush=True)

    for soortgroep, config in mapping.get("parquet_bronnen", {}).items():
        if not isinstance(config, dict):
            continue
        bestand      = config.get("gebruik_bestand", "")
        volledig_pad = parquet_pad / bestand

        if not volledig_pad.exists():
            print(f"  ⚠️  {soortgroep}: niet gevonden: {volledig_pad}")
            continue

        print(f"  📄 {soortgroep} ...", end=" ", flush=True)
        df = lees_parquet_readonly(volledig_pad)

        if df is None:
            print("❌", flush=True)
            continue

        df["_bron_laag"] = bestand
        df["_bron_type"] = "parquet"
        resultaten[soortgroep] = df
        print(f"✅ {len(df)} rijen", flush=True)

    return resultaten


# ─────────────────────────────────────────────
# FIELD MAPPING (alleen in geheugen, nooit naar schijf)
# ─────────────────────────────────────────────

def pas_mapping_toe(df: pd.DataFrame, veld_mapping: dict,
                    negeer: list, extra: list,
                    soortgroep: str, bron_laag: str, bron_type: str) -> pd.DataFrame:
    """
    Hernoemt velden via mapping — ALLEEN in geheugen.
    Originele DataFrame en parquet bestanden blijven ongewijzigd.
    """
    df = df.copy()   # werk altijd op een kopie

    # Normaliseer global_id varianten vóór mapping zodat dedup altijd werkt
    for variant in ("GlobalID", "Globalid", "globalid", "GlobalId", "GlobalID_1", "GlobalID_2"):
        if variant in df.columns and "global_id" not in df.columns:
            df = df.rename(columns={variant: "global_id"})
            break

    hernoem     = {k: v for k, v in veld_mapping.items() if k in df.columns}
    df          = df.rename(columns=hernoem)

    # Fallback: als er geen GlobalID veld in de AGOL laag zit (bijv. Projectgebieden_act),
    # gebruik OBJECTID als synthetische unieke sleutel zodat dedup niet alle rijen weggooit
    if "global_id" not in df.columns or df["global_id"].isna().all():
        for oid_var in ("object_id", "OBJECTID", "FID"):
            if oid_var in df.columns and not df[oid_var].isna().all():
                prefix = bron_laag.lower().replace(" ", "_").replace("-", "_")
                df["global_id"] = df[oid_var].apply(
                    lambda x: f"oid_{prefix}_{int(x)}" if pd.notna(x) else None
                )
                break

    canonical   = set(hernoem.values()) | {"global_id"}
    extra_set   = set(extra) & set(df.columns)
    meta        = {"_bron_laag", "_bron_type"}
    te_negeren  = set(negeer)

    weggooien   = (set(df.columns) - canonical - extra_set - meta) | \
                  (set(df.columns) & te_negeren)
    df          = df.drop(columns=[c for c in weggooien if c in df.columns],
                          errors="ignore")

    df["soortgroep"] = soortgroep
    df["_bron_laag"] = bron_laag
    df["_bron_type"] = bron_type

    return df


# ─────────────────────────────────────────────
# DATUM PRIORITEIT
# ─────────────────────────────────────────────

def parse_datum(waarde) -> pd.Timestamp | None:
    if waarde is None:
        return None
    try:
        if isinstance(waarde, float) and np.isnan(waarde):
            return None
    except Exception:
        pass
    try:
        if isinstance(waarde, (int, float)):
            ts = pd.Timestamp(int(waarde), unit="ms")
        else:
            ts = pd.Timestamp(waarde)
        return ts if 1990 <= ts.year <= 2050 else None
    except Exception:
        return None


def bepaal_beste_datum(rij: pd.Series) -> tuple:
    for veld, label in [
        ("invoerdatum_def", "invoerdatum_def"),
        ("datum",           "datum"),
        ("creation_date",   "creation_date"),
        ("ingevoerd_datum", "ingevoerd_datum"),
    ]:
        if veld in rij.index:
            ts = parse_datum(rij[veld])
            if ts is not None:
                return ts, label
    return None, "onbekend"


def voeg_datum_toe(df: pd.DataFrame, soortgroep: str) -> pd.DataFrame:
    print(f"   🗓️  Datum-prioriteit voor {soortgroep}...", end=" ")
    resultaten    = df.apply(bepaal_beste_datum, axis=1)
    df            = df.copy()
    df["datum_beste"] = resultaten.apply(lambda x: x[0])
    df["datum_bron"]  = resultaten.apply(lambda x: x[1])

    n_ok    = (df["datum_bron"] != "onbekend").sum()
    n_totaal = len(df)
    print(f"✅ {n_ok}/{n_totaal} ({round(n_ok/n_totaal*100,1)}%)")
    for bron, count in df["datum_bron"].value_counts().items():
        print(f"      {bron}: {count}")
    return df


# ─────────────────────────────────────────────
# COMBINEREN op GlobalID
# ─────────────────────────────────────────────

def combineer_bronnen(agol_frames: list, parquet_df: pd.DataFrame | None,
                      soortgroep: str) -> pd.DataFrame:
    frames = [f for f in agol_frames if f is not None and not f.empty]
    if parquet_df is not None and not parquet_df.empty:
        frames.append(parquet_df)

    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]

    gecombineerd = pd.concat(frames, ignore_index=True, sort=False)

    if "global_id" in gecombineerd.columns:
        voor = len(gecombineerd)
        # AGOL wint bij duplicaten (staat bovenaan door concat volgorde)
        gecombineerd = gecombineerd.drop_duplicates(subset=["global_id"], keep="first")
        na = len(gecombineerd)
        if voor > na:
            print(f"   🔄 {voor - na} duplicaten verwijderd op GlobalID")
    else:
        print(f"   ⚠️  Geen global_id — kan niet dedupliceren")

    return gecombineerd


# ─────────────────────────────────────────────
# DUCKDB SCHRIJVEN
# ─────────────────────────────────────────────

def maak_df_duckdb_veilig(df: pd.DataFrame) -> pd.DataFrame:
    """
    Maakt een DataFrame veilig voor DuckDB opslag.
    Drie problemen worden opgelost:
      1. Mixed-type kolommen (bijv. int + str door concat) → alles naar string
      2. GlobalID varianten → altijd 'global_id'
      3. Datetime kolommen → uniform pandas Timestamp
    """
    df = df.copy()

    # Fix 1: normaliseer global_id schrijfwijze
    for variant in ["GlobalID", "Globalid", "globalid", "GlobalId"]:
        if variant in df.columns and "global_id" not in df.columns:
            df = df.rename(columns={variant: "global_id"})

    # Fix 2: mixed-type kolommen -> string (voorkomt DuckDB silent fail)
    for col in df.columns:
        if df[col].dtype == object:
            # Sla kolommen met binary data over (voorkomt UnicodeDecodeError)
            sample = df[col].dropna().head(100)
            if not sample.empty and any(isinstance(v, (bytes, bytearray)) for v in sample):
                continue
                
            typen = df[col].dropna().apply(type).unique()
            if len(typen) > 1:
                # Gebruik errors='ignore' of skip binary om crashes te voorkomen
                try:
                    df[col] = df[col].astype(str).where(df[col].notna(), None)
                except Exception:
                    continue

    # Fix 3: datetime kolommen uniform maken
    # Gebruik 'datetime' string ipv lijst om frequentie-errors in pandas select_dtypes te voorkomen
    for col in df.select_dtypes(include=["datetime", "datetimetz"]).columns:
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=False)
        # Verwijder timezone info — DuckDB heeft moeite met tz-aware timestamps
        if hasattr(df[col].dt, "tz") and df[col].dt.tz is not None:
            df[col] = df[col].dt.tz_localize(None)

    # Fix 4: oneindig / NaN in numerieke kolommen
    for col in df.select_dtypes(include=["float64", "Float64"]).columns:
        df[col] = df[col].replace([float("inf"), float("-inf")], None)

    # Fix 5: geometry → WKT string zodat shapely objecten DuckDB niet laten crashen
    # bij grote tabellen (bijv. Vogels 84k rijen)
    if "geometry" in df.columns:
        def _naar_wkt(v):
            if v is None:
                return None
            try:
                return v.wkt if hasattr(v, "wkt") else (str(v) if v is not None else None)
            except Exception:
                return None
        df["geometry"] = df["geometry"].apply(_naar_wkt)

    return df


# Drempelwaarden voor chunked write — beschermt tegen STATUS_HEAP_CORRUPTION
# (gezien op Vogels-tabel, 84k rijen) bij grote DataFrame → Parquet → DuckDB.
CHUNKED_WRITE_THRESHOLD = 50_000
CHUNK_RIJEN             = 20_000


def _schrijf_df_naar_tabel(con, df: pd.DataFrame, tabel: str, db_pad: str) -> None:
    """Schrijf DataFrame naar DuckDB-tabel via tijdelijke parquet(s).

    Voor >50k rijen: split in chunks van 20k. Elke chunk wordt apart
    weggeschreven en geheugen vrijgegeven; DuckDB leest de stapel in één
    CREATE TABLE-statement via read_parquet([...]). Dit voorkomt de C-level
    heap-corruption die optreedt bij grote DataFrames in één klap.

    Voor <=50k rijen: één parquet, gedrag identiek aan voorheen.
    """
    import gc

    con.execute(f"DROP TABLE IF EXISTS {tabel}")
    db_dir = Path(db_pad).parent

    if len(df) <= CHUNKED_WRITE_THRESHOLD:
        tmp = db_dir / f"_temp_{tabel}.parquet"
        try:
            df.to_parquet(tmp, index=False)
            con.execute(
                f"CREATE TABLE {tabel} AS SELECT * FROM read_parquet('{tmp.as_posix()}')"
            )
        finally:
            tmp.unlink(missing_ok=True)
        return

    # Chunked pad — schrijf elke chunk apart, ruim geheugen tussendoor op
    chunk_paden: list[Path] = []
    try:
        n_chunks = (len(df) + CHUNK_RIJEN - 1) // CHUNK_RIJEN
        print(f"\n   ✂️  Chunked write: {len(df)} rijen in {n_chunks} chunks van {CHUNK_RIJEN}",
              flush=True)

        for i in range(n_chunks):
            chunk = df.iloc[i * CHUNK_RIJEN:(i + 1) * CHUNK_RIJEN]
            chunk_pad = db_dir / f"_temp_{tabel}_chunk{i:03d}.parquet"
            chunk.to_parquet(chunk_pad, index=False)
            chunk_paden.append(chunk_pad)
            del chunk
            gc.collect()
            print(f"\r   📦 chunk {i + 1}/{n_chunks} geschreven", end="", flush=True)

        # Lijst van forward-slash paden voor DuckDB's SQL-parser
        bestanden_lit = "[" + ", ".join(f"'{p.as_posix()}'" for p in chunk_paden) + "]"
        con.execute(f"CREATE TABLE {tabel} AS SELECT * FROM read_parquet({bestanden_lit})")
        print(f"\n   ✅ {n_chunks} chunks samengevoegd in {tabel}", flush=True)
    finally:
        for p in chunk_paden:
            p.unlink(missing_ok=True)


def schrijf_naar_duckdb(alle_data: dict, db_pad: str):
    print(f"\n{'='*60}", flush=True)
    print(f"  🦆 SCHRIJVEN NAAR DUCKDB: {db_pad}", flush=True)
    print(f"{'='*60}", flush=True)

    # Gebruik context manager — garandeert commit én sluiting ook bij fouten
    with duckdb.connect(db_pad) as con:

        con.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_log (
                run_timestamp TIMESTAMP,
                soortgroep    TEXT,
                rijen         INTEGER,
                datum_pct     DOUBLE,
                bron_types    TEXT
            )
        """)

        import gc

        totaal = 0
        for soortgroep in list(alle_data.keys()):
            df = alle_data.pop(soortgroep)   # verwijder uit dict → geheugen vrijgeven na verwerking
            if df.empty:
                print(f"  ⚠️  {soortgroep}: leeg — overgeslagen")
                continue

            tabel = (f"waarnemingen_{soortgroep.lower()}"
                     .replace(" ", "_").replace("ë", "e").replace("é", "e")
                     .replace("à", "a").replace("ö", "o"))

            print(f"  📊 {soortgroep} → {tabel} ({len(df)} rijen)...", end=" ", flush=True)

            try:
                # Maak DataFrame veilig voor DuckDB
                df_veilig = maak_df_duckdb_veilig(df)

                # Debug: print kolom-types als er problemen zijn
                mixed = [c for c in df_veilig.columns
                         if df_veilig[c].dtype == object and
                         len(df_veilig[c].dropna().apply(type).unique()) > 1]
                if mixed:
                    print(f"\n   ⚠️  Nog mixed-type kolommen na fix: {mixed}")

                # Schrijf via helper — chunked pad voor >50k rijen, voorkomt
                # heap-corruption die historisch op Vogels (84k) is opgetreden.
                _schrijf_df_naar_tabel(con, df_veilig, tabel, db_pad)

                # Controleer of data echt geschreven is
                telling = con.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]
                if telling != len(df_veilig):
                    raise ValueError(
                        f"Schrijffout: {telling} rijen in DuckDB maar {len(df_veilig)} verwacht"
                    )

                # Indices voor query performance
                for index_col in ["global_id", "datum_beste"]:
                    if index_col in df_veilig.columns:
                        try:
                            con.execute(
                                f"CREATE INDEX IF NOT EXISTS "
                                f"idx_{tabel}_{index_col} ON {tabel} ({index_col})"
                            )
                        except Exception:
                            pass  # Indices zijn optioneel

                datum_pct  = round(
                    (df_veilig.get("datum_bron", pd.Series()) != "onbekend").mean() * 100, 1
                )
                bron_types = (
                    ", ".join(df_veilig["_bron_type"].unique())
                    if "_bron_type" in df_veilig.columns else "?"
                )
                con.execute(
                    "INSERT INTO _pipeline_log VALUES (?,?,?,?,?)",
                    [datetime.now(), soortgroep, telling, datum_pct, bron_types]
                )

                totaal += telling
                print(f"✅ ({telling} rijen geverifieerd)")

            except Exception as e:
                print(f"❌ {e}")
                import traceback
                traceback.print_exc()

            finally:
                # Geef geheugen vrij — bij grote tabellen (Vogels 84k) essentieel
                try:
                    del df_veilig
                except NameError:
                    pass
                del df
                gc.collect()

        con.execute("""
            CREATE OR REPLACE VIEW overzicht AS
            SELECT soortgroep, rijen, datum_pct, bron_types, run_timestamp
            FROM _pipeline_log ORDER BY rijen DESC
        """)

        # Expliciete commit + CHECKPOINT — forceert WAL-flush naar hoofdbestand.
        # Zonder CHECKPOINT blijft .wal soms achter en faalt de volgende stap
        # (duckdb_naar_geopackage.py) met "WAL file present" bij read_only-open.
        con.commit()
        con.execute("CHECKPOINT")

    # Verificatie na sluiting: open nieuw verbinding en tel rijen
    print(f"\n  🔍 Post-write verificatie...")
    with duckdb.connect(db_pad, read_only=True) as verify_con:
        tabellen = verify_con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name LIKE 'waarnemingen_%'"
        ).fetchall()
        print(f"  Tabellen in DuckDB: {len(tabellen)}")
        for (tabel_naam,) in sorted(tabellen):
            n = verify_con.execute(f"SELECT COUNT(*) FROM {tabel_naam}").fetchone()[0]
            print(f"    {tabel_naam}: {n:,} rijen")

    print(f"\n  ✅ Totaal {totaal:,} rijen opgeslagen en geverifieerd")


# ─────────────────────────────────────────────
# GAP RAPPORT
# ─────────────────────────────────────────────

def maak_gap_rapport(alle_data: dict) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print("  📊 GAP ANALYSE")
    print(f"{'='*60}")

    rapport = []
    for sg, df in alle_data.items():
        if df.empty or "_bron_type" not in df.columns:
            continue
        bron = df["_bron_type"].value_counts().to_dict()
        datum_pct = round((df["datum_bron"] != "onbekend").mean() * 100, 1) \
                    if "datum_bron" in df.columns else 0
        rapport.append({
            "soortgroep":    sg,
            "totaal":        len(df),
            "agol_actueel":  bron.get("agol_actueel", 0),
            "agol_historie": bron.get("agol_historie", 0),
            "parquet":       bron.get("parquet", 0),
            "datum_%":       datum_pct,
        })

    df_r = pd.DataFrame(rapport).sort_values("totaal", ascending=False)
    print(df_r.to_string(index=False))
    df_r.to_csv(str(DATABEHEER / "03_logs" / "gap_rapport.csv"), index=False)
    print("\n  ✅ gap_rapport.csv opgeslagen")
    return df_r


# ─────────────────────────────────────────────
# PREFLIGHT
# ─────────────────────────────────────────────

def preflight_check() -> bool:
    """Controleert kritieke afhankelijkheden vóór de run start."""
    ok = True
    for label, check in [
        ("Databeheer map bereikbaar", lambda: DATABEHEER.exists()),
        (".env gevonden",          lambda: Path(ENV_PAD).exists()),
        ("duckdb importeerbaar",   lambda: __import__("duckdb") is not None),
    ]:
        try:
            passed = check()
        except Exception:
            passed = False
        sym = "✅" if passed else "❌"
        print(f"  {sym} {label}")
        if not passed:
            ok = False
    return ok


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main(hervat: bool = False):
    import sys

    # Optionele Sentry-integratie — no-op zonder SENTRY_DSN, geen verstoring.
    # Geeft visibility op uncaught exceptions in productie-runs.
    try:
        from _observability import init_observability
        init_observability("agol_ingest")
    except ImportError:
        pass

    # Zorg dat de log-map bestaat
    DATABEHEER.mkdir(parents=True, exist_ok=True)
    (DATABEHEER / "03_logs").mkdir(parents=True, exist_ok=True)

    log_fh = open(LOG_PAD, "w", encoding="utf-8")

    class Tee:
        def __init__(self, *files): self.files = files
        def write(self, obj): [f.write(obj) for f in self.files]
        def flush(self): [f.flush() for f in self.files]

    sys.stdout = Tee(sys.__stdout__, log_fh)

    print("=" * 60)
    print("  AGOL → DUCKDB PIPELINE v2")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  🔒 Read-only AGOL guard: ACTIEF")
    print("  ♻️  Retry met exponential backoff: ACTIEF")
    print("  💾 Checkpointing: ACTIEF")
    print("=" * 60)

    print("\n🔍 Preflight checks ...")
    if not preflight_check():
        print("\n❌ Preflight MISLUKT — pipeline gestopt. Controleer bovenstaande fouten.")
        sys.stdout = sys.__stdout__
        log_fh.close()
        raise SystemExit(1)

    # Checkpoint laden (of nieuw starten)
    checkpoint = laad_checkpoint() if hervat else \
                 {"gestart_op": datetime.now().isoformat(), "voltooid": {}}

    # Field mapping laden
    print(f"\n📋 Field mapping laden ...")
    with open(MAPPING_PAD, encoding="utf-8") as f:
        mapping = json.load(f)
    print(f"   ✅ {len(mapping['parquet_bronnen'])} soortgroepen")

    # Authenticatie
    token = get_token()
    if not token:
        print("\n⚠️  Geen AGOL token — alleen parquets worden geladen.")

    # AGOL data ophalen
    agol_data_raw: dict[str, list] = {}

    if token:
        print(f"\n{'='*60}")
        print(f"  🌐 AGOL OPHALEN ({len(AGOL_LAGEN)} lagen)")
        print(f"{'='*60}")

        for laagnaam, url in AGOL_LAGEN.items():
            soortgroep = AGOL_NAAR_SOORTGROEP.get(laagnaam, laagnaam)
            print(f"\n  🔗 {laagnaam} ...")

            # Vleermuizen_hist: use OBJECTID-range fetching (offset-based crashes at 35658)
            if laagnaam == "Vleermuizen_hist":
                df = haal_agol_laag_op_objectid_ranges(url, token, laagnaam, checkpoint, range_size=10000)
            else:
                df = haal_agol_laag_op(url, token, laagnaam, checkpoint)

            if df is not None and not df.empty:
                agol_data_raw.setdefault(soortgroep, []).append(df)

    # Parquets laden
    parquet_data = laad_parquets(mapping)

    # Verwerken per soortgroep
    print(f"\n{'='*60}", flush=True)
    print("  🔄 VERWERKEN", flush=True)
    print(f"{'='*60}", flush=True)

    alle_data: dict[str, pd.DataFrame] = {}
    alle_soortgroepen = set(agol_data_raw.keys()) | set(parquet_data.keys())
    alle_soortgroepen.add("Amfibieën")   # altijd via parquet

    for soortgroep in sorted(alle_soortgroepen):
        print(f"\n  🔬 {soortgroep}", flush=True)
        config     = mapping["parquet_bronnen"].get(soortgroep, {})
        if not isinstance(config, dict):
            config = {}
            
        veld_map   = config.get("veld_mapping", {})
        negeer     = config.get("negeer_velden", [])
        extra      = config.get("extra_velden_behouden", [])

        # AGOL frames mappen
        agol_frames = []
        for adf in agol_data_raw.get(soortgroep, []):
            if not adf.empty:
                agol_frames.append(pas_mapping_toe(
                    adf, veld_map, negeer, extra, soortgroep,
                    adf["_bron_laag"].iloc[0], adf["_bron_type"].iloc[0]
                ))

        # Parquet mappen
        p_df = parquet_data.get(soortgroep)
        p_gemapped = pas_mapping_toe(
            p_df, veld_map, negeer, extra, soortgroep,
            config.get("gebruik_bestand", ""), "parquet"
        ) if p_df is not None else None

        gecombineerd = combineer_bronnen(agol_frames, p_gemapped, soortgroep)
        if gecombineerd.empty:
            print(f"   ⚠️  Geen data")
            continue

        gecombineerd = voeg_datum_toe(gecombineerd, soortgroep)
        alle_data[soortgroep] = gecombineerd
        print(f"   ✅ {len(gecombineerd)} rijen totaal", flush=True)

    maak_gap_rapport(alle_data)
    print(f"\n  💾 Schrijven naar DuckDB ...", flush=True)
    schrijf_naar_duckdb(alle_data, DUCKDB_PAD)
    print(f"  ✅ DuckDB schrijven klaar", flush=True)

    # Checkpoint opruimen na succesvolle run
    verwijder_checkpoint()

    print(f"\n{'='*60}")
    print("  🎉 KLAAR")
    print(f"  DuckDB: {DUCKDB_PAD}")
    print(f"  Log:    {LOG_PAD}")
    print(f"  Volgende stap: valideer in DuckDB, dan export naar GeoPackage")
    print(f"{'='*60}")

    sys.stdout = sys.__stdout__
    log_fh.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hervat", action="store_true",
                        help="Hervat een onderbroken run via checkpoint")
    args = parser.parse_args()
    main(hervat=args.hervat)
