"""
PostGIS: domein-opzoektabellen aanmaken + Value Relation setup
==============================================================
Leest domains_snapshot.json en maakt per uniek domein een opzoektabel
in het ewaarnemingen schema. QGIS Value Relation widgets verwijzen
daarnaar i.p.v. ValueMap — betere performance bij grote lijsten (Flora: 5650 soorten).

Maakt ook:
  - ewaarnemingen.veldwerk_invoer   ← schrijfbare tabel voor nieuwe QField-observaties
  - Rechten correct per rol

Gebruik:
    python postgis_domeinen_aanmaken.py
    python postgis_domeinen_aanmaken.py --dry-run
"""

import json
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(r'C:\GIS_Projecten\.env')
load_dotenv(Path(__file__).parent.parent / '.env')

import psycopg2
from psycopg2 import sql

# ── Config ────────────────────────────────────────────────────────────────────
DOMAINS_PAD = Path(__file__).parent.parent / 'Databeheer' / '00_kern' / 'domains_snapshot.json'

PG_HOST   = os.getenv('PG_HOST',          'localhost')
PG_PORT   = os.getenv('PG_PORT',          '5432')
PG_DB     = os.getenv('PG_DB',            'ewaarnemingen')
PG_SCHEMA = os.getenv('PG_SCHEMA',        'ewaarnemingen')
PG_USER   = os.getenv('PG_ADMIN_USER',    'postgres')
PG_PASS   = os.getenv('PG_ADMIN_PASS',    '')

# Combinaties laagnaam_veldnaam die te groot zijn voor een keuzemenu
# (ongewervelden soort: 9361, paddestoelen: 7107, flora Latijn: 5650)
SLA_OVER = {'ongewervelden_soort', 'paddestoelen_soort', 'flora_latijnse_naam'}


def laad_domeinen():
    with open(DOMAINS_PAD, encoding='utf-8') as f:
        snap = json.load(f)

    domeinen = {}           # {tabel_naam: {code: label}}
    domein_per_veld = {}    # {laagnaam: {veldnaam_lower: tabel_naam}}

    for laagnaam, laagdata in snap.get('lagen', {}).items():
        domein_per_veld[laagnaam] = {}
        for veld in laagdata.get('schema', {}).get('velden', []):
            if veld.get('domein_type') != 'codedValue':
                continue
            if not veld.get('domein_waarden'):
                continue

            veld_lower = veld['naam'].lower()
            sleutel = f"{laagnaam}_{veld_lower}"
            if sleutel in SLA_OVER:
                continue  # Te groot voor keuzemenu, weglaten

            dn = veld.get('domein_naam', '').lower().replace(' ', '_').replace('-', '_')
            if not dn or len(dn) > 40:
                # Gebruik laagnaam + veldnaam als de domein_naam ontbreekt of te lang is (bijv. UUID)
                dn = f"{laagnaam}_{veld_lower}"[:40]
            tabel_naam = f"domein_{dn}"

            domeinen[tabel_naam] = veld['domein_waarden']
            domein_per_veld[laagnaam][veld_lower] = tabel_naam

    return domeinen, domein_per_veld


def maak_domein_tabellen(con, domeinen, dry_run):
    aangemaakt = 0
    bijgewerkt = 0
    cur = con.cursor() if con else None

    for tabel_naam, waarden in sorted(domeinen.items()):
        # Tabel: domein_XXX met kolommen: code TEXT, label TEXT
        ddl = f"""
            CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{tabel_naam} (
                code  TEXT PRIMARY KEY,
                label TEXT NOT NULL
            );
        """
        if dry_run:
            print(f'  [dry-run] {tabel_naam}: {len(waarden)} waarden')
            continue

        cur.execute(ddl)

        # Huidige inhoud vergelijken
        cur.execute(f'SELECT COUNT(*) FROM {PG_SCHEMA}.{tabel_naam}')
        huidig = cur.fetchone()[0]

        if huidig != len(waarden):
            # Truncate + opnieuw vullen
            cur.execute(f'TRUNCATE {PG_SCHEMA}.{tabel_naam}')
            rijen = [(code, label) for code, label in waarden.items()]
            cur.executemany(
                f'INSERT INTO {PG_SCHEMA}.{tabel_naam} (code, label) VALUES (%s, %s)',
                rijen
            )
            bijgewerkt += 1
            print(f'  Bijgewerkt: {tabel_naam} ({len(waarden)} waarden)')
        else:
            aangemaakt += 1

        # Leesrechten voor alle rollen
        cur.execute(f'GRANT SELECT ON {PG_SCHEMA}.{tabel_naam} TO ew_beheer, ew_collega, ew_pipeline')

    if not dry_run:
        con.commit()
        print(f'\n  {aangemaakt} ongewijzigd, {bijgewerkt} bijgewerkt/aangemaakt')


def maak_veldwerk_tabel(con, dry_run):
    """
    Schrijfbare invoertabel voor nieuwe veldwaarnemingen via QField.
    Bevat de meest gebruikte velden, gekoppeld aan domein-tabellen.
    Volledig apart van de read-only waarnemingen_* tabellen.
    """
    ddl = f"""
        CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.veldwerk_invoer (
            id              SERIAL PRIMARY KEY,
            invoer_datum    TIMESTAMP DEFAULT NOW(),
            invoer_door     TEXT DEFAULT current_user,
            status          TEXT DEFAULT 'nieuw' CHECK (status IN ('nieuw', 'gecontroleerd', 'verwerkt')),

            -- Kern-observatievelden
            soortgroep      TEXT NOT NULL,
            soort           TEXT,
            aantal          NUMERIC,
            gedrag          TEXT,
            geslacht        TEXT,
            stadium         TEXT,
            telmethode      TEXT,
            opmerking       TEXT,
            datum           DATE DEFAULT CURRENT_DATE,
            waarnemer       TEXT,

            -- Locatie
            geometry        geometry(Point, 28992),
            locatie_naam    TEXT,
            project         TEXT,

            -- Referentie naar bestaande AGOL-laag (optioneel)
            agol_global_id  TEXT,
            bron_laag       TEXT,

            -- Metadata
            device_id       TEXT,
            qfield_versie   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_veldwerk_datum    ON {PG_SCHEMA}.veldwerk_invoer (datum);
        CREATE INDEX IF NOT EXISTS idx_veldwerk_soort    ON {PG_SCHEMA}.veldwerk_invoer (soort);
        CREATE INDEX IF NOT EXISTS idx_veldwerk_status   ON {PG_SCHEMA}.veldwerk_invoer (status);
        CREATE INDEX IF NOT EXISTS idx_veldwerk_geom     ON {PG_SCHEMA}.veldwerk_invoer USING GIST (geometry);
    """

    rechten = f"""
        GRANT SELECT, INSERT, UPDATE ON {PG_SCHEMA}.veldwerk_invoer TO ew_beheer, ew_collega;
        GRANT SELECT ON {PG_SCHEMA}.veldwerk_invoer TO ew_readonly;
        GRANT USAGE ON SEQUENCE {PG_SCHEMA}.veldwerk_invoer_id_seq TO ew_beheer, ew_collega;
    """

    rij_beveiliging = f"""
        -- Row-level security: collega's zien alleen hun eigen invoer
        ALTER TABLE {PG_SCHEMA}.veldwerk_invoer ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS veldwerk_eigen_rijen ON {PG_SCHEMA}.veldwerk_invoer;
        CREATE POLICY veldwerk_eigen_rijen ON {PG_SCHEMA}.veldwerk_invoer
            FOR ALL TO ew_collega
            USING (invoer_door = current_user)
            WITH CHECK (invoer_door = current_user);

        DROP POLICY IF EXISTS veldwerk_beheer_alles ON {PG_SCHEMA}.veldwerk_invoer;
        CREATE POLICY veldwerk_beheer_alles ON {PG_SCHEMA}.veldwerk_invoer
            FOR ALL TO ew_beheer
            USING (true)
            WITH CHECK (true);
    """

    if dry_run:
        print('\n  [dry-run] veldwerk_invoer tabel aanmaken')
        print('  [dry-run] Row-level security: ew_collega ziet alleen eigen rijen')
        return

    cur = con.cursor()
    cur.execute(ddl)
    cur.execute(rechten)
    cur.execute(rij_beveiliging)
    con.commit()
    print('\n  ✓ veldwerk_invoer aangemaakt met row-level security')
    print('    ew_collega: kan invoeren + eigen rijen zien/bewerken')
    print('    ew_beheer:  ziet en bewerkt alles, kan status bijwerken')


def druk_qgis_instructies(domein_per_veld):
    """Druk per laag de Value Relation configuratie af voor in QGIS."""
    print('\n' + '=' * 60)
    print('  QGIS Value Relation configuratie')
    print('  Stel dit in via: Layer Properties → Attributes Form')
    print('=' * 60)

    for laagnaam, velden in sorted(domein_per_veld.items()):
        if not velden:
            continue
        print(f'\n  Laag: waarnemingen_{laagnaam}')
        for veldnaam, domein_tabel in sorted(velden.items()):
            print(f'    Veld "{veldnaam}":')
            print(f'      Widget: Value Relation')
            print(f'      Layer:  {domein_tabel}  (in PostGIS schema ewaarnemingen)')
            print(f'      Key:    code')
            print(f'      Value:  label')
            print(f'      Filter: (leeg laten)')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Toon wat er zou gebeuren zonder te schrijven')
    args = parser.parse_args()

    print('=' * 60)
    print('  POSTGIS DOMEINEN AANMAKEN')
    if args.dry_run:
        print('  MODE: DRY-RUN')
    print('=' * 60)

    domeinen, domein_per_veld = laad_domeinen()
    print(f'\n  {len(domeinen)} unieke domein-tabellen te maken')

    if not args.dry_run:
        try:
            con = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, dbname=PG_DB,
                user=PG_USER, password=PG_PASS
            )
            con.autocommit = False
            print(f'  PostgreSQL verbinding OK ({PG_USER}@{PG_HOST})\n')
        except Exception as e:
            print(f'FOUT: PostgreSQL onbereikbaar: {e}')
            sys.exit(1)
    else:
        con = None

    print('  Domein-tabellen:')
    maak_domein_tabellen(con, domeinen, args.dry_run)
    maak_veldwerk_tabel(con, args.dry_run)

    if con:
        con.close()

    druk_qgis_instructies(domein_per_veld)

    print('\n' + '=' * 60)
    print('  KLAAR')
    print('=' * 60)


if __name__ == '__main__':
    main()
