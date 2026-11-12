"""Async database engine and schema migrations."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from inky_image_display_api.config import Settings

logger = logging.getLogger(__name__)

# Migrations ship inside the package so they are available in the installed wheel.
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "_migrations"


def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLAlchemy engine from settings.

    Args:
        settings: Application settings containing ``database_url``.

    Returns:
        Configured async engine.

    """
    return create_async_engine(settings.database_url)


async def create_tables(engine: AsyncEngine) -> None:
    """Ensure the application schema is present and up-to-date.

    Everything — including the create_all bootstrap of base tables that no
    migration creates — happens inside the Alembic run (see
    ``_migrations/env.py``), so the app's startup and a bare
    ``alembic upgrade head`` build the exact same schema.

    Args:
        engine: Async database engine.

    """
    if not _MIGRATIONS_DIR.exists():
        logger.warning("Migrations dir not found at %s — skipping migrations", _MIGRATIONS_DIR)
        return

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))

    def _upgrade(connection: Connection) -> None:
        # Handing Alembic our connection (instead of a URL) keeps it on the
        # app's engine and transaction; env.py must not open its own engine,
        # or an ambient API_DATABASE_PATH could migrate a different file.
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)
