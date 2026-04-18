"""CLI entrypoint for the Inky Image Display Sync service."""

import asyncio
import logging
from typing import Annotated

import typer
from inky_image_display_shared.logging import setup_logging

from inky_image_display_sync.immich import DisplayAPIClient, ImmichSyncService
from inky_image_display_sync.immich.config import APIClientConfig

app = typer.Typer(help="Immich Sync for Inky Image Display")


@app.callback(invoke_without_command=True)
def main(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show jobs that would be synced")] = False,
) -> None:
    """Sync images from Immich to local storage.

    Executes all active sync jobs from the Display API. Each job defines filters
    and selection criteria for fetching images from Immich.

    Configuration is via environment variables:
    - IMMICH_BASE_URL: Immich server URL
    - IMMICH_API_KEY: API key for authentication
    - S3_WRITER_*: S3-compatible connection for image storage
    - DISPLAY_API_BASE_URL: Base URL for the Display API service
    """
    asyncio.run(run_immich_sync(dry_run))


async def run_immich_sync(dry_run: bool) -> None:
    """Run the Immich sync operation for all active jobs.

    Args:
        dry_run: If True, only show what would be synced

    """
    setup_logging()
    logger = logging.getLogger("inky_image_display_sync")

    api_config = APIClientConfig()  # ty: ignore[missing-argument]
    api_client = DisplayAPIClient(config=api_config, logger=logger)

    try:
        if dry_run:
            jobs = await api_client.get_active_sync_jobs()
            if not jobs:
                logger.warning("No active sync jobs found")
                return
            logger.info("Dry run mode - would process %d job(s):", len(jobs))
            for job in jobs:
                logger.info("  - %s: strategy=%s, count=%d", job.name, job.strategy, job.count)
            return

        sync_service = ImmichSyncService(
            api_client=api_client,
            logger=logger,
        )
        await sync_service.sync_all_active_jobs()
    finally:
        await api_client.aclose()


if __name__ == "__main__":
    app()
