"""Alembic env.py — leest PostgreSQL-credentials uit .env.

Standaard alembic-env aangepast zodat sqlalchemy.url uit C:\\GIS_Projecten\\.env
komt — credentials staan NOOIT in alembic.ini of versie-bestanden.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ── Credentials uit .env ──────────────────────────────────────────────────────

_DB_DIR = Path(__file__).parent.parent
_PROJECT_DIR = _DB_DIR.parent  # ArcGIS_online/

load_dotenv(r"C:\GIS_Projecten\.env")
load_dotenv(_PROJECT_DIR / ".env")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB   = os.getenv("PG_DB",   "ewaarnemingen")
PG_USER = os.getenv("PG_ADMIN_USER", os.getenv("PG_PIPELINE_USER", "postgres"))
PG_PASS = os.getenv("PG_ADMIN_PASS", os.getenv("PG_PIPELINE_PASS", ""))

if not PG_PASS:
    raise RuntimeError(
        "Geen PG_ADMIN_PASS / PG_PIPELINE_PASS in .env — alembic kan niet verbinden."
    )

config.set_main_option(
    "sqlalchemy.url",
    f"postgresql+psycopg2://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}",
)


# ── Target metadata ───────────────────────────────────────────────────────────
# Voor nu: geen SQLAlchemy-modellen → autogenerate uitgeschakeld.
# Zodra we modellen definiëren (sprint 2+), import hier en wijs aan:
#   from db.models import Base
#   target_metadata = Base.metadata
target_metadata = None

# Beperk alembic tot het 'ewaarnemingen'-schema (laat 'public' met rust)
TARGET_SCHEMA = os.getenv("PG_SCHEMA", "ewaarnemingen")


def include_object(obj, name, type_, reflected, compare_to):
    """Filter: alleen objecten in TARGET_SCHEMA meenemen."""
    if type_ == "table" and getattr(obj, "schema", None) != TARGET_SCHEMA:
        return False
    return True


def run_migrations_offline() -> None:
    """Genereer SQL zonder verbinding (voor review)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=TARGET_SCHEMA,
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Voer migrations uit met live connectie naar PostgreSQL."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=TARGET_SCHEMA,
            include_schemas=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
