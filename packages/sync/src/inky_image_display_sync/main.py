"""CLI entrypoint for the Inky Image Display Sync service."""

import asyncio
import logging
from typing import Annotated

import sqlalchemy
import typer
from inky_image_display_shared.models.device import Device
from inky_image_display_shared.models.image import Image
from inky_image_display_shared.models.immich_sync_job import ImmichSyncJob
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_sync.immich import ImmichSyncService
from inky_image_display_sync.immich.config import DatabaseConfig

app = typer.Typer(help="Immich Sync for Inky Image Display")


@app.callback(invoke_without_command=True)
def main(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show jobs that would be synced")] = False,
) -> None:
    """Sync images from Immich to local storage.

    Executes all active sync jobs from the database. Each job defines filters
    and selection criteria for fetching images from Immich.

    Configuration is via environment variables:
    - IMMICH_BASE_URL: Immich server URL
    - IMMICH_API_KEY: API key for authentication
    - S3_WRITER_*: S3-compatible connection for image storage
    - POSTGRES_*: Database connection
    """
    asyncio.run(run_immich_sync(dry_run))


async def run_immich_sync(dry_run: bool) -> None:
    """Run the Immich sync operation for all active jobs.

    Args:
        dry_run: If True, only show what would be synced

    """
    logger = logging.getLogger("inky_image_display_sync")

    db_config = DatabaseConfig()  # ty: ignore[missing-argument]
    db_engine = create_async_engine(db_config.url)

    # Ensure required tables exist (Device first for FK ordering)
    async with db_engine.begin() as conn:
        for table in [Device.__table__, Image.__table__, ImmichSyncJob.__table__]:  # ty: ignore[unresolved-attribute]
            await conn.run_sync(table.create, checkfirst=True)

    if dry_run:
        async with AsyncSession(db_engine) as session:
            stmt = select(ImmichSyncJob).where(ImmichSyncJob.is_active == sqlalchemy.true())
            db_result = await session.exec(stmt)
            jobs = list(db_result.all())

        if not jobs:
            logger.warning("No active sync jobs found")
            return

        logger.info("Dry run mode - would process %d job(s):", len(jobs))
        for job in jobs:
            logger.info("  - %s: strategy=%s, count=%d", job.name, job.strategy, job.count)
        return

    # Run sync for all active jobs
    sync_service = ImmichSyncService(
        engine=db_engine,
        logger=logger,
    )

    await sync_service.sync_all_active_jobs()


if __name__ == "__main__":
    app()
