"""Alembic runtime environment.

Reads the DB URL from DATABASE_URL (same var the app uses) instead of
alembic.ini, so no credentials are committed and migrations target whatever
DB the current environment points at.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import the app's metadata so `alembic revision --autogenerate` *could* be
# used later; our hand-written migration doesn't need it, but target_metadata
# lets autogenerate diff against the models if we ever want it.
from app.database import Base
from app import models  # noqa: F401  (imported for its side effect: registers Document on Base)

config = context.config

# Inject the URL from the environment into Alembic's config at runtime.
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (alembic upgrade --sql)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
