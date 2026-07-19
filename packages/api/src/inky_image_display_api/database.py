"""Async database engine, table initialisation, and Alembic migrations."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from inky_image_display_shared.models import (
    Device,
    DisplayJob,
    DisplayJobSlot,
    GeminiSyncJob,
    GenerationTask,
    Grid,
    GridDevice,
    Image,
    ImmichSyncJob,
    MotdMessage,
    MotdScreen,
    PromptBlock,
    PromptPreset,
    SyncJobRun,
)
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

    For fresh databases: creates all tables from the current SQLModel
    metadata, so startup works without an existing schema.

    For any database: runs Alembic migrations to ``head`` so column-level
    changes (which ``create_all`` cannot apply to existing tables) are
    picked up. Migrations are written to be idempotent on fresh DBs.

    Args:
        engine: Async database engine.

    """
    async with engine.begin() as conn:
        tables = [
            Image.__table__,  # ty: ignore[unresolved-attribute]
            Grid.__table__,  # ty: ignore[unresolved-attribute]
            PromptBlock.__table__,  # ty: ignore[unresolved-attribute]
            PromptPreset.__table__,  # ty: ignore[unresolved-attribute]
            Device.__table__,  # ty: ignore[unresolved-attribute]
            GridDevice.__table__,  # ty: ignore[unresolved-attribute]
            ImmichSyncJob.__table__,  # ty: ignore[unresolved-attribute]
            GeminiSyncJob.__table__,  # ty: ignore[unresolved-attribute]
            # display_jobs precedes motd_messages: the message FK references
            # it, and referenced tables must exist at DDL time.
            DisplayJob.__table__,  # ty: ignore[unresolved-attribute]
            DisplayJobSlot.__table__,  # ty: ignore[unresolved-attribute]
            MotdMessage.__table__,  # ty: ignore[unresolved-attribute]
            MotdScreen.__table__,  # ty: ignore[unresolved-attribute]
            SyncJobRun.__table__,  # ty: ignore[unresolved-attribute]
            GenerationTask.__table__,  # ty: ignore[unresolved-attribute]
        ]
        for table in tables:
            await conn.run_sync(table.create, checkfirst=True)

    await _run_alembic_upgrade(engine)


async def _run_alembic_upgrade(engine: AsyncEngine) -> None:
    """Apply Alembic migrations up to ``head`` using the engine's URL."""
    if not _MIGRATIONS_DIR.exists():
        logger.warning("Migrations dir not found at %s — skipping migrations", _MIGRATIONS_DIR)
        return

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    # Alembic runs synchronously; rewrite the async URL to its sync equivalent.
    sync_url = str(engine.url).replace("+aiosqlite", "").replace("+asyncpg", "")
    cfg.set_main_option("sqlalchemy.url", sync_url)

    def _upgrade() -> None:
        command.upgrade(cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(lambda _sync_conn: _upgrade())
