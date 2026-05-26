# PostGIS schema-migraties (Alembic)

Schemawijzigingen aan het `ewaarnemingen`-schema in PostgreSQL gaan vanaf nu
via Alembic — versioned, reviewable, terug te draaien. Geen handmatige
`ALTER TABLE` meer.

## Status — mei 2026

**Bootstrap-fase.** De structuur staat klaar maar er zijn nog **geen migrations**.
De huidige tabellen (`waarnemingen_*` etc.) zijn aangemaakt door
`duckdb_naar_postgis.py` zonder versionering. Voordat we de eerste migration
schrijven moeten we:

1. **Schemarichting bepalen** (gaat ergens in Sprint 2 / vóór QField-rollout):
   - Blijven 17 losse tabellen, of één gepartitioneerde `observations`?
   - FK's naar `domains.*` of doorgaan met string-velden?
   - Permissies-model (`ew_admin`, `ew_editor`, `ew_field`, `ew_viewer`)?
2. **Baseline migration** schrijven die de huidige staat beschrijft.
3. **`alembic stamp head`** draaien op de bestaande DB zodat hij weet
   dat baseline al toegepast is.

## Setup (eenmalig per omgeving)

```powershell
# Alembic + driver installeren (in venv)
pip install alembic psycopg2-binary python-dotenv sqlalchemy

# Credentials in C:\GIS_Projecten\.env (al aanwezig):
#   PG_ADMIN_USER=postgres
#   PG_ADMIN_PASS=...
#   PG_HOST=localhost
#   PG_DB=ewaarnemingen
#   PG_SCHEMA=ewaarnemingen
```

## Workflow voor een nieuwe schemawijziging

```powershell
cd C:\GIS_Projecten\ArcGIS_online\db

# 1. Nieuwe lege migration aanmaken
alembic -c alembic.ini revision -m "korte_omschrijving"

# 2. Bewerk versions/YYYYMMDD_HHMM_korte_omschrijving.py:
#    - upgrade(): de SQL/Operations om naar de nieuwe staat te gaan
#    - downgrade(): hoe je terugkomt naar de vorige staat
#    Voorbeeld:
#      op.add_column('waarnemingen_vogels',
#                    sa.Column('uploaded_by', sa.String(100)),
#                    schema='ewaarnemingen')

# 3. Test eerst de SQL die wordt gegenereerd
alembic -c alembic.ini upgrade head --sql > /tmp/wijziging.sql
# Lees /tmp/wijziging.sql door — alleen wat je verwacht?

# 4. Toepassen op DB
alembic -c alembic.ini upgrade head

# 5. Status checken
alembic -c alembic.ini current
alembic -c alembic.ini history

# 6. Terugdraaien (bij issue)
alembic -c alembic.ini downgrade -1
```

## Veiligheid

- **Secrets**: `alembic.ini` heeft een placeholder; échte URL komt uit `.env`
  via `env.py`. Commit NOOIT credentials in dit bestand.
- **Schemafilter**: `env.py` filtert op `PG_SCHEMA` zodat alembic alleen
  `ewaarnemingen.*` tabellen ziet — laat `public.*` met rust.
- **Backups**: `snapshot.py` maakt elke pipeline-run een `pg_dump`. Vóór
  een grote migration: handmatig extra snapshot draaien.

## Waarom Alembic en niet handmatige SQL

- Versionering (welke migrations zijn waar toegepast?)
- Downgrade-pad (terugdraaien is expliciet)
- Code-review (migration in een PR, vier ogen)
- Multi-omgeving (dezelfde wijzigingen op test → prod)
- Audit-trail (`alembic_version` tabel toont history)

## Niet-Alembic SQL

Sommige operaties horen niet bij alembic:
- Grants/permissies → eigen SQL-bestanden onder `db/grants/`
- Row-level security policies → idem
- Materialized views voor analytics → idem

Reden: deze moeten vaak idempotent draaien en zijn niet "schema-state" in
de Alembic-zin.
