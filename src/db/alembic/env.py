import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool
from alembic import context

# Load .env if present (local dev; Docker injects env vars directly)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import ALL models so autogenerate captures all three schemas
from src.db.models.base import Base
from src.db.models import cvm, bacen, b3_calc  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Read DATABASE_URL from environment — no hardcoded strings (INFRA-05)
database_url = os.environ["DATABASE_URL"]
# Ensure asyncpg dialect
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
config.set_main_option("sqlalchemy.url", database_url)


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,                # CRITICAL: detects non-public schemas
        version_table_schema="public",       # alembic_version stays in public schema
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # one-shot: no connection reuse
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


def run_migrations_offline():
    # Offline mode not needed for this project; raise to avoid silent no-op
    raise NotImplementedError("Offline migration mode is not supported in this project")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
