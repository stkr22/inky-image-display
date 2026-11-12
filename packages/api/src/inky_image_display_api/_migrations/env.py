"""Alembic environment configuration for inky-image-display-api."""

import os
from logging.config import fileConfig

from alembic import context

# Importing the bootstrap module registers every model on SQLModel.metadata,
# which both autogenerate and the bootstrap below read from.
from inky_image_display_api._migrations.bootstrap import bootstrap_schema, target_metadata
from sqlalchemy import Connection, engine_from_config, pool

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


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


def _run(connection: Connection) -> None:
    bootstrap_schema(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations on the app's connection, or a CLI-built engine.

    The app passes its own connection via ``config.attributes`` so the
    migration targets exactly the database it is serving. Only the bare
    CLI (``alembic upgrade head``) falls back to a URL, where
    ``API_DATABASE_PATH`` overrides alembic.ini's placeholder.
    """
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    database_path = os.environ.get("API_DATABASE_PATH")
    if database_path:
        # Alembic runs synchronously — use plain sqlite:/// (no aiosqlite driver)
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as conn:
        _run(conn)
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
