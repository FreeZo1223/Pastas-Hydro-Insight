"""
DuckDB → PostGIS export
=======================
Exporteert alle waarnemingen-tabellen vanuit ewaarnemingen.duckdb
naar het PostGIS-schema 'ewaarnemingen' op localhost.

Gebruik:
    python duckdb_naar_postgis.py            # volledige export (truncate + herlaad)
    python duckdb_naar_postgis.py --dry-run  # alleen tellen, niets schrijven

Vereisten:
    pip install geopandas sqlalchemy psycopg2-binary python-dotenv
"""

import argparse
import os
import sys
from pathlib import Path

import json

import duckdb
import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv
from shapely import wkb, wkt
from shapely.geometry import shape
from sqlalchemy import create_engine, text

# ── Config ────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent

# Laad globale .env (PostgreSQL credentials) + project .env (AGOL etc.)
load_dotenv(r"C:\GIS_Projecten\.env")
load_dotenv(_PROJECT_DIR / ".env")

DUCKDB_PAD = _PROJECT_DIR / "Databeheer" / "00_kern" / "ewaarnemingen.duckdb"

PG_HOST     = os.getenv("PG_HOST",          "localhost")
PG_PORT     = os.getenv("PG_PORT",          "5432")
PG_DB       = os.getenv("PG_DB",            "ewaarnemingen")
PG_SCHEMA   = os.getenv("PG_SCHEMA",        "ewaarnemingen")
PG_USER     = os.getenv("PG_PIPELINE_USER", "ew_pipeline")
PG_PASS     = os.getenv("PG_PIPELINE_PASS", "")

# Lagen die worden overgeslagen (geen structurele AGOL-data)
EXCLUDE = {"waarnemingen_baarn_vleermuizen", "waarnemingen_baarn_vogels"}

TARGET_CRS = "EPSG:28992"  # RD New


# ── Geometry parsing ──────────────────────────────────────────────────────────

def _parse_geometry(val):
    """Zet DuckDB geometry-waarde om naar Shapely. Drie formats: GeoJSON, WKB, WKT."""
    if val is None:
        return None
    try:
        if isinstance(val, (bytes, bytearray)):
            b = bytes(val)
            if b[:1] == b"{":
                return shape(json.loads(b.decode("utf-8")))
            try:
                return wkb.loads(b)
            except Exception:
                return wkt.loads(b.decode("utf-8", errors="replace"))
        if isinstance(val, str):
            if val.strip().startswith("{"):
                return shape(json.loads(val))
            return wkt.loads(val)
    except Exception:
        return None
    return None


def _detecteer_crs(geoms: list) -> str:
    """Bepaal CRS op basis van coördinaatbereik: RD New als meerderheid binnen NL-bounds."""
    rd_count = 0
    total = 0
    for g in geoms:
        if g is None:
            continue
        try:
            x, y = g.centroid.x, g.centroid.y
            if 7000 < x < 300000 and 289000 < y < 629000:
                rd_count += 1
            total += 1
        except Exception:
            continue
    if total == 0:
        return "EPSG:4326"
    return "EPSG:28992" if rd_count > total / 2 else "EPSG:4326"


# ── Tabel naar GeoDataFrame ───────────────────────────────────────────────────

def tabel_naar_gdf(con, tabel: str) -> gpd.GeoDataFrame | None:
    df = con.execute(f"SELECT * FROM {tabel}").df()

    if "geometry" not in df.columns:
        return df

    df["geometry"] = df["geometry"].apply(_parse_geometry)

    geoms_met = [g for g in df["geometry"] if g is not None]
    if not geoms_met:
        # Tabel heeft geometry-kolom maar alle waarden zijn NULL — schrijf zonder geom
        return df.drop(columns=["geometry"])

    bron_crs = _detecteer_crs(geoms_met)
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=bron_crs)
    if bron_crs != TARGET_CRS:
        try:
            gdf = gdf.to_crs(TARGET_CRS)
        except Exception as e:
            print(f"   ⚠️  CRS-conversie mislukt: {e}")

    n_null = df["geometry"].isna().sum()
    if n_null:
        print(f"   ℹ️  {n_null} rijen zonder geometry (blijven als NULL in PostGIS)")

    return gdf


# ── Exporteer naar PostGIS ────────────────────────────────────────────────────


def _tabel_bestaat(engine, schema: str, tabel_naam: str) -> bool:
    """Bestaat de tabel al in dit schema?"""
    sql = text(
        "SELECT EXISTS (SELECT 1 FROM pg_tables "
        "WHERE schemaname = :schema AND tablename = :tabel)"
    )
    with engine.connect() as conn:
        return bool(conn.execute(sql, {"schema": schema, "tabel": tabel_naam}).scalar())


def exporteer_tabel(gdf, engine, tabel_naam: str, schema: str, dry_run: bool) -> int:
    """Schrijf naar PostGIS via TRUNCATE+INSERT (preserveert grants/views/indices).

    Bij eerste run (tabel bestaat niet): `if_exists="replace"` om kolomtypes te
    creëren. Bij vervolg-runs: TRUNCATE binnen transactie + INSERT — table
    identity blijft behouden zodat permissies, views en indices niet wegvallen.
    """
    if dry_run:
        n = len(gdf) if hasattr(gdf, '__len__') else 0
        print(f"   [dry-run] {tabel_naam}: {n:,} rijen")
        return n

    bestaat = _tabel_bestaat(engine, schema, tabel_naam)

    if bestaat:
        # TRUNCATE + INSERT in één transactie: bij crash blijft oude data staan.
        # RESTART IDENTITY voor het geval er ooit een serial PK bij komt.
        with engine.begin() as conn:
            conn.execute(text(f'TRUNCATE TABLE "{schema}"."{tabel_naam}" RESTART IDENTITY'))
            if isinstance(gdf, gpd.GeoDataFrame):
                gdf.to_postgis(tabel_naam, conn, schema=schema,
                               if_exists="append", index=False, chunksize=5000)
            else:
                gdf.to_sql(tabel_naam, conn, schema=schema,
                           if_exists="append", index=False, chunksize=5000)
    else:
        # Eerste run voor deze tabel — laat geopandas/pandas de DDL bepalen.
        if isinstance(gdf, gpd.GeoDataFrame):
            gdf.to_postgis(tabel_naam, engine, schema=schema,
                           if_exists="replace", index=False, chunksize=5000)
        else:
            gdf.to_sql(tabel_naam, engine, schema=schema,
                       if_exists="replace", index=False, chunksize=5000)

    return len(gdf)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Tellen zonder iets naar PostGIS te schrijven")
    args = parser.parse_args()

    print("=" * 60)
    print("  DUCKDB → POSTGIS EXPORT")
    print(f"  Database: {PG_HOST}:{PG_PORT}/{PG_DB}  schema: {PG_SCHEMA}")
    if args.dry_run:
        print("  MODE: DRY-RUN (niets geschreven)")
    print("=" * 60)

    if not DUCKDB_PAD.exists():
        print(f"FOUT: DuckDB niet gevonden: {DUCKDB_PAD}")
        sys.exit(1)

    # Verbinding PostgreSQL
    conn_str = f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    try:
        engine = create_engine(conn_str)
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        print(f"✅ PostgreSQL verbinding OK ({PG_USER}@{PG_HOST})")
    except Exception as e:
        print(f"FOUT: PostgreSQL onbereikbaar: {e}")
        sys.exit(1)

    # DuckDB openen
    con = duckdb.connect(str(DUCKDB_PAD), read_only=True)
    tabellen = [r[0] for r in con.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name LIKE 'waarnemingen_%'
        ORDER BY table_name
    """).fetchall()]

    tabellen_actief = [t for t in tabellen if t not in EXCLUDE]
    print(f"\n📋 {len(tabellen_actief)} tabellen te exporteren "
          f"({len(EXCLUDE)} uitgesloten)\n")

    totaal = 0
    fouten = []

    for tabel in tabellen_actief:
        naam_kort = tabel.replace("waarnemingen_", "")
        print(f"  🔄 {naam_kort} ...", end=" ", flush=True)
        try:
            gdf = tabel_naar_gdf(con, tabel)
            if gdf is None or (hasattr(gdf, '__len__') and len(gdf) == 0):
                print("leeg, overgeslagen")
                continue
            n = exporteer_tabel(gdf, engine, tabel, PG_SCHEMA, args.dry_run)
            print(f"{n:,} rijen ✅")
            totaal += n
        except Exception as e:
            print(f"FOUT: {e}")
            fouten.append((naam_kort, str(e)))

    con.close()

    print(f"\n{'=' * 60}")
    print(f"  Totaal geëxporteerd: {totaal:,} rijen")
    if fouten:
        print(f"  Fouten ({len(fouten)}):")
        for naam, fout in fouten:
            print(f"    ❌ {naam}: {fout}")
    else:
        print("  Geen fouten")
    print("=" * 60)

    sys.exit(1 if fouten else 0)


if __name__ == "__main__":
    main()
