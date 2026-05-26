"""
DuckDB → GeoPackage Export Script
===================================
Exporteert alle waarnemingen-tabellen uit DuckDB naar:
  1. GeoPackage per soortgroep  (voor AGOL / ArcGIS Pro)
  2. Parquet backup per soortgroep (voor J-schijf archief)

VEILIGHEIDSGARANTIES:
  ✅ Leest alleen uit DuckDB — schrijft NOOIT terug
  ✅ Wijzigt NOOIT de originele parquet bestanden
  ✅ Schrijft NOOIT naar AGOL — dat doe je handmatig via ArcGIS Pro

Na dit script:
  → Open ArcGIS Pro
  → Catalog pane → voeg GeoPackage toe
  → Klik rechts op laag → Share → Overwrite Web Layer
    OF: Share → Web Feature Layer (publish) voor nieuwe laag

Vereisten:
    pip install duckdb pandas pyarrow geopandas shapely

Gebruik:
    python duckdb_naar_geopackage.py
"""

import json
import os
import warnings
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Callable

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────
# ATOMIC WRITE HELPER
# ─────────────────────────────────────────────

def schrijf_atomair(doel: Path, schrijf_fn: Callable[[Path], None]) -> None:
    """Schrijf via .tmp + os.replace zodat een crash mid-write nooit een
    gedeeltelijk bestand achterlaat. os.replace() is atomic op NTFS.

    schrijf_fn krijgt het tmp-pad en moet daarnaar schrijven.
    """
    doel.parent.mkdir(parents=True, exist_ok=True)
    tmp = doel.with_name(doel.name + ".tmp")
    if tmp.exists():
        # Restant van vorige mislukte run — opruimen voordat we beginnen.
        tmp.unlink()
    try:
        schrijf_fn(tmp)
        # fsync zodat data écht op schijf staat voordat we renamen.
        try:
            fd = os.open(str(tmp), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass  # fsync werkt niet op alle filesystems — best-effort
        os.replace(tmp, doel)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

# ─────────────────────────────────────────────
# CONFIG — pas paden aan indien nodig
# ─────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent

DUCKDB_PAD      = str(_PROJECT_DIR / "Databeheer" / "00_kern" / "ewaarnemingen.duckdb")
MAPPING_PAD     = str(_PROJECT_DIR / "Databeheer" / "05_context" / "field_mapping.json")

# Export bestemmingen — lokaal (C:) en J:-schijf
# QGIS_MAP: vaste bestandsnamen zonder datum → QGIS wijst hier altijd naar
LOKAAL_EXPORTS  = str(_PROJECT_DIR / "Databeheer" / "02_geopackage" / "exports")
LOKAAL_QGIS     = str(_PROJECT_DIR / "Databeheer" / "02_geopackage" / "qgis")
J_EXPORTS       = r"J:/Databeheer/Ewaarnemingen_databeheer/02_geopackage/exports"
J_QGIS          = r"J:/Databeheer/Ewaarnemingen_databeheer/02_geopackage/qgis"
J_PARQUET       = r"J:/Databeheer/Ewaarnemingen_databeheer/01_parquet/actueel"

DATUM_VANDAAG   = datetime.now().strftime("%Y-%m-%d")

# Drempel voor waarschuwingsvlag in bestandsnaam
DATUM_WAARSCHUWING_PCT = 50.0

# ─────────────────────────────────────────────
# OMGEKEERDE FIELD MAPPING
# (canonical DuckDB naam → originele AGOL veldnaam)
# ─────────────────────────────────────────────

def maak_omgekeerde_mapping(mapping: dict, soortgroep: str) -> dict:
    """
    Keert de veld_mapping om: DuckDB canonical → AGOL veldnaam.
    Gebruikt voor export zodat ArcGIS Pro de veldnamen herkent.

    Voorbeeld:
      field_mapping:  "Soort" → "soort"
      omgekeerd:      "soort" → "Soort"

    Bij conflicten (meerdere bronvelden → zelfde canonical):
    wordt de eerste mapping gebruikt.
    """
    config = mapping.get("parquet_bronnen", {}).get(soortgroep, {})
    veld_map = config.get("veld_mapping", {})

    omgekeerd = {}
    for agol_naam, canonical_naam in veld_map.items():
        # Sla systeemvelden over
        if canonical_naam.startswith("_"):
            continue
        # Eerste mapping wint bij conflicten
        if canonical_naam not in omgekeerd:
            omgekeerd[canonical_naam] = agol_naam

    return omgekeerd


# ─────────────────────────────────────────────
# GEOMETRY HERSTEL
# ─────────────────────────────────────────────

def _is_rd_new(geom) -> bool:
    """Detecteer of een geometry in RD New (EPSG:28992) staat op basis van coördinaten."""
    try:
        b = geom.bounds  # (minx, miny, maxx, maxy)
        # RD New: X 0–280000, Y 300000–625000
        return 0 < b[0] < 280000 and 300000 < b[1] < 625000
    except Exception:
        return False


def herstel_geometry(df: pd.DataFrame) -> tuple:
    """
    Zet geometry kolom om naar Shapely geometrie voor GeoPackage export.
    Ondersteunt:
      - GeoJSON string
      - GeoJSON als bytes (UTF-8)
      - WKB bytes (bijv. RD New van parquet-bronnen)

    Retourneert (df_met_shapely_geom, bron_crs_string).
    bron_crs is 'EPSG:28992' als WKB-RD-New gedetecteerd, anders 'EPSG:4326'.
    """
    try:
        from shapely.geometry import shape
        from shapely import wkb as shapely_wkb
        import json as json_mod

        def parse_geom(waarde):
            if waarde is None or (isinstance(waarde, float) and np.isnan(waarde)):
                return None
            # Stap 1: normaliseer bytes → string indien GeoJSON
            if isinstance(waarde, (bytes, bytearray)):
                try:
                    waarde_str = waarde.decode("utf-8")
                    geoj = json_mod.loads(waarde_str)
                    return shape(geoj)
                except Exception:
                    pass
                # Stap 2: probeer WKB
                try:
                    return shapely_wkb.loads(bytes(waarde))
                except Exception:
                    return None
            # Stap 3: string → GeoJSON
            if isinstance(waarde, str):
                try:
                    geoj = json_mod.loads(waarde)
                    return shape(geoj)
                except Exception:
                    return None
            return None

        df = df.copy()
        df["geometry"] = df["geometry"].apply(parse_geom)

        n_leeg = df["geometry"].isna().sum()
        n_totaal = len(df)
        if n_leeg > 0:
            print(f"   ⚠️  {n_leeg}/{n_totaal} rijen zonder geometry (NULL in brondata)")

        # Detecteer CRS: als meerderheid van geldige geometrieën RD New-coördinaten heeft
        geldig = df["geometry"].dropna()
        if len(geldig) > 0:
            n_rd = sum(1 for g in geldig if _is_rd_new(g))
            bron_crs = "EPSG:28992" if n_rd > len(geldig) / 2 else "EPSG:4326"
        else:
            bron_crs = "EPSG:4326"

        return df, bron_crs

    except ImportError:
        print("   ⚠️  shapely niet gevonden — GeoPackage zonder geometry")
        df["geometry"] = None
        return df, "EPSG:4326"


# ─────────────────────────────────────────────
# EXPORT FUNCTIES
# ─────────────────────────────────────────────

def exporteer_naar_geopackage(df: pd.DataFrame, bestandspad: Path,
                               laagnaam: str) -> bool:
    """
    Exporteer DataFrame naar GeoPackage.
    Vereist geopandas voor schrijven met geometry.
    Valt terug op export zonder geometry als geopandas ontbreekt.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        df_geom, bron_crs = herstel_geometry(df)

        # Maak GeoDataFrame met gedetecteerde CRS
        gdf = gpd.GeoDataFrame(df_geom, geometry="geometry", crs=bron_crs)

        # Reprojecteer alles naar RD New (EPSG:28992) — Dutch standaard voor QGIS
        if bron_crs != "EPSG:28992" and gdf.geometry.notna().any():
            gdf = gdf.to_crs("EPSG:28992")
        print(f"   CRS: {bron_crs} -> EPSG:28992", end="  ")

        # Verwijder kolommen die GeoPackage niet aankan
        for col in gdf.columns:
            if gdf[col].dtype == object:
                # Converteer lijsten/dicts naar string
                gdf[col] = gdf[col].apply(
                    lambda x: str(x) if isinstance(x, (list, dict)) else x
                )

        # Atomair schrijven: bij crash mid-write blijft de oude GPKG intact.
        schrijf_atomair(
            bestandspad,
            lambda tmp: gdf.to_file(str(tmp), layer=laagnaam, driver="GPKG"),
        )
        return True

    except ImportError:
        print("   ⚠️  geopandas niet gevonden — sla op als CSV als fallback")
        csv_pad = bestandspad.with_suffix(".csv")
        schrijf_atomair(csv_pad, lambda tmp: df.to_csv(tmp, index=False))
        print(f"   💾 Fallback CSV: {csv_pad}")
        return False
    except Exception as e:
        print(f"   ❌ GeoPackage fout: {e}")
        return False


def exporteer_naar_parquet(df: pd.DataFrame, bestandspad: Path) -> bool:
    """Exporteer DataFrame naar Parquet (backup formaat), atomair."""
    try:
        # Geometry als string bewaren in parquet (GeoJSON)
        df_backup = df.copy()
        if "geometry" in df_backup.columns:
            df_backup["geometry"] = df_backup["geometry"].astype(str)
        schrijf_atomair(
            bestandspad,
            lambda tmp: df_backup.to_parquet(tmp, index=False),
        )
        return True
    except Exception as e:
        print(f"   ❌ Parquet fout: {e}")
        return False


# ─────────────────────────────────────────────
# KWALITEITSCHECK
# ─────────────────────────────────────────────

def check_kwaliteit(df: pd.DataFrame, soortgroep: str) -> dict:
    """Geef een kwaliteitsoverzicht van de data voor export."""
    n = len(df)
    rapport = {
        "soortgroep":   soortgroep,
        "totaal_rijen": n,
        "datum_pct":    0.0,
        "soort_pct":    0.0,
        "geometry_pct": 0.0,
        "waarschuwingen": [],
    }

    if "datum_bron" in df.columns:
        datum_pct = round((df["datum_bron"] != "onbekend").mean() * 100, 1)
        rapport["datum_pct"] = datum_pct
        if datum_pct < DATUM_WAARSCHUWING_PCT:
            rapport["waarschuwingen"].append(f"datum slechts {datum_pct}%")

    if "soort" in df.columns:
        soort_pct = round(df["soort"].notna().mean() * 100, 1)
        rapport["soort_pct"] = soort_pct
        if soort_pct < 70:
            rapport["waarschuwingen"].append(f"soort slechts {soort_pct}%")

    if "geometry" in df.columns:
        geom_pct = round(df["geometry"].notna().mean() * 100, 1)
        rapport["geometry_pct"] = geom_pct
        if geom_pct < 80:
            rapport["waarschuwingen"].append(f"geometry slechts {geom_pct}%")

    return rapport


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  DUCKDB → GEOPACKAGE EXPORT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Maak exportmappen aan — J: alleen als bereikbaar
    j_beschikbaar = Path(r"J:\\").exists()
    lokale_mappen = [LOKAAL_EXPORTS, LOKAAL_QGIS]
    j_mappen = [J_EXPORTS, J_QGIS, J_PARQUET] if j_beschikbaar else []
    for map_pad in lokale_mappen + j_mappen:
        Path(map_pad).mkdir(parents=True, exist_ok=True)
    if not j_beschikbaar:
        print("⚠️  J:-schijf niet bereikbaar — export alleen naar C:")

    # Laad field mapping
    print(f"\n📋 Field mapping laden...")
    with open(MAPPING_PAD, encoding="utf-8") as f:
        mapping = json.load(f)

    # Open DuckDB (read-only — we schrijven NOOIT terug)
    print(f"\n🦆 DuckDB openen (read-only): {DUCKDB_PAD}")
    con = duckdb.connect(DUCKDB_PAD, read_only=True)

    # Haal lijst van alle waarnemingen-tabellen op
    tabellen = con.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name LIKE 'waarnemingen_%'
        ORDER BY table_name
    """).fetchall()

    print(f"   {len(tabellen)} tabellen gevonden in DuckDB\n")

    resultaten = []

    for (tabel_naam,) in tabellen:

        # Bepaal soortgroep uit tabelnaam
        soortgroep_raw = tabel_naam.replace("waarnemingen_", "").replace("_", " ").title()
        # Herstel speciale tekens
        soortgroep_raw = soortgroep_raw.replace("Amfibieen", "Amfibieën")

        print(f"{'='*60}")
        print(f"  📦 {tabel_naam} ({soortgroep_raw})")

        # Lees data uit DuckDB
        df = con.execute(f"SELECT * FROM {tabel_naam}").df()
        print(f"  Rijen: {len(df):,} | Velden: {len(df.columns)}")

        # Kwaliteitscheck
        kwaliteit = check_kwaliteit(df, soortgroep_raw)
        if kwaliteit["waarschuwingen"]:
            for w in kwaliteit["waarschuwingen"]:
                print(f"  ⚠️  Waarschuwing: {w}")

        # Bestandsnaam — met waarschuwingsvlag als datum laag is
        vlag = "_LET_OP_LAGE_DATUMKWALITEIT" \
               if kwaliteit["datum_pct"] < DATUM_WAARSCHUWING_PCT else ""
        # Gedateerde naam voor exports/archief
        basis_naam = f"{soortgroep_raw.replace(' ', '_')}_{DATUM_VANDAAG}{vlag}"
        # Vaste naam zonder datum voor QGIS (wordt elke run overschreven)
        qgis_naam = soortgroep_raw.replace(' ', '_').lower()

        # Omgekeerde field mapping toepassen
        # (canonical DuckDB naam → originele AGOL veldnaam)
        omgekeerde_map = maak_omgekeerde_mapping(mapping, soortgroep_raw)
        if omgekeerde_map:
            df = df.rename(columns=omgekeerde_map)
            print(f"  🔄 {len(omgekeerde_map)} velden hernoemd naar AGOL namen")
        else:
            print(f"  ℹ️  Geen omgekeerde mapping beschikbaar — canonical namen bewaard")

        # Behoud altijd datum_beste en datum_bron als extra kolommen
        # (staan niet in originele AGOL schema maar zijn waardevol)
        # Ze worden als extra kolommen meegeëxporteerd

        # ── Export 1: GeoPackage gedateerd (lokaal + J:, voor archief/ArcGIS Pro) ──
        lokaal_export_pad = Path(LOKAAL_EXPORTS) / f"{basis_naam}.gpkg"
        print(f"  💾 Export (lokaal) → {lokaal_export_pad.name} ...", end=" ")
        ok_gpkg = exporteer_naar_geopackage(df.copy(), lokaal_export_pad, soortgroep_raw)
        if ok_gpkg:
            grootte = round(lokaal_export_pad.stat().st_size / 1_000_000, 2)
            print(f"✅ ({grootte} MB)")

        if j_beschikbaar:
            j_export_pad = Path(J_EXPORTS) / f"{basis_naam}.gpkg"
            print(f"  💾 Export (J:)     → {j_export_pad.name} ...", end=" ")
            ok_j = exporteer_naar_geopackage(df.copy(), j_export_pad, soortgroep_raw)
            if ok_j:
                print(f"✅")

        # ── Export 2: GeoPackage vaste naam voor QGIS (lokaal + J:, wordt overschreven) ──
        lokaal_qgis_pad = Path(LOKAAL_QGIS) / f"{qgis_naam}.gpkg"
        print(f"  💾 QGIS (lokaal)   → {lokaal_qgis_pad.name} ...", end=" ")
        ok_qgis_lokaal = exporteer_naar_geopackage(df.copy(), lokaal_qgis_pad, soortgroep_raw)
        if ok_qgis_lokaal:
            print(f"✅")

        if j_beschikbaar:
            j_qgis_pad = Path(J_QGIS) / f"{qgis_naam}.gpkg"
            print(f"  💾 QGIS (J:)       → {j_qgis_pad.name} ...", end=" ")
            ok_qgis_j = exporteer_naar_geopackage(df.copy(), j_qgis_pad, soortgroep_raw)
            if ok_qgis_j:
                print(f"✅")

            # ── Export 3: Parquet actueel naar J-schijf (voor collega-analyses) ──
            parquet_pad = Path(J_PARQUET) / f"{qgis_naam}.parquet"
            print(f"  💾 Parquet (J:)    → {parquet_pad.name} ...", end=" ")
            ok_parquet = exporteer_naar_parquet(df.copy(), parquet_pad)
            if ok_parquet:
                grootte = round(parquet_pad.stat().st_size / 1_000_000, 2)
                print(f"✅ ({grootte} MB)")

        resultaten.append({
            "soortgroep":   soortgroep_raw,
            "rijen":        len(df),
            "datum_%":      kwaliteit["datum_pct"],
            "gpkg_ok":      ok_gpkg,
            "qgis_ok":      ok_qgis_j if j_beschikbaar else ok_qgis_lokaal,
            "parquet_ok":   ok_parquet if j_beschikbaar else None,
            "waarschuwingen": " | ".join(kwaliteit["waarschuwingen"]) or "geen",
        })

    con.close()

    # ── Exportrapport ──
    print(f"\n{'='*60}")
    print("  📊 EXPORTRAPPORT")
    print(f"{'='*60}")
    df_rapport = pd.DataFrame(resultaten)
    print(df_rapport.to_string(index=False))
    df_rapport.to_csv("export_rapport.csv", index=False)

    # ── Instructies voor ArcGIS Pro ──
    print(f"""
{'='*60}
  ✅ EXPORT KLAAR — VOLGENDE STAP IN ARCGIS PRO
{'='*60}

Lokale GeoPackages staan in:
  {LOKAAL_EXPORTS}

Per soortgroep kun je kiezen:

  OPTIE A — Nieuwe laag publiceren (VEILIGST):
  1. Open ArcGIS Pro
  2. Catalog pane → voeg GeoPackage toe
  3. Klik rechts op laag → Share as Web Feature Layer
  4. Naam: bijv. Vogels_historie_hersteld
  5. Valideer in webmap → schakel om als akkoord

  OPTIE B — Bestaande _historie laag overschrijven:
  1. Open ArcGIS Pro
  2. Voeg GeoPackage laag toe aan project
  3. Klik rechts op laag → Sharing → Overwrite Web Layer
  4. Selecteer de bestaande AGOL _historie laag

  ⚠️  Lagen met LET_OP_LAGE_DATUMKWALITEIT in naam:
  Controleer deze eerst handmatig voor publicatie.
{'='*60}
""")


if __name__ == "__main__":
    main()
