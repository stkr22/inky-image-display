"""Alembic environment configuration for inky-image-display-api."""

import os
from logging.config import fileConfig

from alembic import context
from inky_image_display_shared.models import (
    Device,
    DeviceProfile,
    GeminiSyncJob,
    Grid,
    GridDevice,
    Image,
    ImmichSyncJob,
    PromptBlock,
    PromptPreset,
)
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
database_path = os.environ.get("API_DATABASE_PATH")
if database_path:
    # Alembic runs synchronously — use plain sqlite:/// (no aiosqlite driver)
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

# Keep references so the models are registered on the metadata — both
# autogenerate and the create_all bootstrap in run_migrations_online read from
# SQLModel.metadata, so every owned table must be imported here.
_models = (Device, DeviceProfile, GeminiSyncJob, Grid, GridDevice, Image, ImmichSyncJob, PromptBlock, PromptPreset)

# Tables create_all may bootstrap before migrations run. This must mirror
# database.create_tables exactly: device_profiles and app_settings are
# deliberately excluded because the migrations own them — 0007 seeds
# device_profiles with its then-current columns and 0008 adds the rest, so
# pre-creating the current (NOT NULL) shape would break 0007's seed.
_BOOTSTRAP_MODELS = (Image, Grid, Device, GridDevice, ImmichSyncJob, PromptBlock, PromptPreset, GeminiSyncJob)


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

        # Mirror the app's hybrid bootstrap (see database.create_tables): the
        # base tables are owned by create_all and the migrations only apply
        # incremental changes on top, guarded to be no-ops on a fresh schema.
        # Creating them here first means a bare ``alembic upgrade head`` against
        # an empty database produces the same complete schema the app builds at
        # startup, instead of crashing on a migration (e.g. 0007) that
        # references a table no migration creates. ``checkfirst=True`` makes
        # this a no-op on databases that already have the tables.
        target_metadata.create_all(
            connection,
            tables=[model.__table__ for model in _BOOTSTRAP_MODELS],  # ty: ignore[unresolved-attribute]
            checkfirst=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
