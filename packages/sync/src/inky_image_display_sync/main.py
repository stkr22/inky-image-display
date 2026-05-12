"""CLI entrypoint for the Inky Image Display Sync service.

Defaults to running the Immich sync (back-compat with the original
single-command invocation) but also exposes a ``gemini`` subcommand for
AI-generated batches.
"""

import asyncio
import logging
from typing import Annotated

import typer
from inky_image_display_shared.logging import setup_logging

from inky_image_display_sync.gemini import GeminiSyncService
from inky_image_display_sync.gemini.api_client import GeminiDisplayAPIClient
from inky_image_display_sync.immich import ImmichDisplayAPIClient, ImmichSyncService
from inky_image_display_sync.immich.config import APIClientConfig

app = typer.Typer(help="Sync service for Inky Image Display (Immich + Gemini)")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show jobs that would be synced")] = False,
) -> None:
    """Default action: run Immich sync (back-compat). Use ``gemini`` for AI batch."""
    if ctx.invoked_subcommand is not None:
        return
    asyncio.run(run_immich_sync(dry_run))


@app.command()
def immich(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show jobs that would be synced")] = False,
) -> None:
    """Run Immich sync for all active sync jobs."""
    asyncio.run(run_immich_sync(dry_run))


@app.command()
def gemini(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show jobs that would be generated")] = False,
) -> None:
    """Run Gemini batch generation for all active Gemini sync jobs."""
    asyncio.run(run_gemini_sync(dry_run))


async def run_immich_sync(dry_run: bool) -> None:
    """Run the Immich sync operation for all active jobs."""
    setup_logging()
    logger = logging.getLogger("inky_image_display_sync")

    api_config = APIClientConfig()  # ty: ignore[missing-argument]
    api_client = ImmichDisplayAPIClient(config=api_config, logger=logger)

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


async def run_gemini_sync(dry_run: bool) -> None:
    """Run Gemini batch generation for all active Gemini sync jobs."""
    setup_logging()
    logger = logging.getLogger("inky_image_display_sync")

    api_config = APIClientConfig()  # ty: ignore[missing-argument]
    api_client = GeminiDisplayAPIClient(config=api_config, logger=logger)

    try:
        if dry_run:
            jobs = await api_client.get_active_gemini_jobs()
            if not jobs:
                logger.warning("No active Gemini sync jobs found")
                return
            logger.info("Dry run mode - would process %d Gemini job(s):", len(jobs))
            for job in jobs:
                total = len(job.subjects) * job.images_per_subject
                logger.info(
                    "  - %s: %d subjects x %d = %d images",
                    job.name,
                    len(job.subjects),
                    job.images_per_subject,
                    total,
                )
            return

        service = GeminiSyncService(api_client=api_client, logger=logger)
        await service.sync_all_active_jobs()
    finally:
        await api_client.aclose()


if __name__ == "__main__":
    app()
