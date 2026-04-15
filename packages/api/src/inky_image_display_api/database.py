"""Async database engine and table initialisation."""

from inky_image_display_shared.models import Device, Image, ImmichSyncJob
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from inky_image_display_api.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLAlchemy engine from settings.

    Args:
        settings: Application settings containing ``database_url``.

    Returns:
        Configured async engine.

    """
    return create_async_engine(settings.database_url, pool_pre_ping=True)


async def create_tables(engine: AsyncEngine) -> None:
    """Create application tables if they do not exist.

    Only creates the three tables owned by the API service.

    Args:
        engine: Async database engine.

    """
    async with engine.begin() as conn:
        for table in [Image.__table__, Device.__table__, ImmichSyncJob.__table__]:  # ty: ignore[unresolved-attribute]
            await conn.run_sync(table.create, checkfirst=True)
