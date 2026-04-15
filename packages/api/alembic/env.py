"""Alembic environment configuration for inky-image-display-api."""

import os
from logging.config import fileConfig

from alembic import context
from inky_image_display_shared.models import Device, Image, ImmichSyncJob
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata — only the tables the API owns
target_metadata = SQLModel.metadata

# Override sqlalchemy.url from env var when available
database_url = os.environ.get("API_DATABASE_URL")
if database_url:
    # Alembic runs synchronously — swap asyncpg for psycopg2
    sync_url = database_url.replace("+asyncpg", "+psycopg2")
    config.set_main_option("sqlalchemy.url", sync_url)

# Keep references so the models are registered on the metadata
_models = (Device, Image, ImmichSyncJob)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
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
