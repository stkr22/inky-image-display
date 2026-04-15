"""CLI entry point for the Inky Display Controller."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Annotated

import typer

from inky_image_display_controller.config import load_settings
from inky_image_display_controller.controller import DisplayController

app = typer.Typer(
    name="inky-controller",
    help="Inky Display Controller - E-ink display management daemon for Raspberry Pi.",
    add_completion=False,
)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: If True, set log level to DEBUG.

    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@app.command()
def main(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to YAML configuration file.",
            exists=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    device_id: Annotated[
        str | None,
        typer.Option(
            "--device-id",
            "-d",
            help="Device identifier (overrides config file).",
            envvar="DEVICE_ID",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Enable verbose debug logging.",
        ),
    ] = False,
) -> None:
    """Start the Inky Display Controller daemon.

    The controller connects to the Inky Image Display API via WebSocket,
    registers with the server, and displays images received via commands.
    """
    setup_logging(verbose=verbose)
    logger = logging.getLogger(__name__)

    # Load settings
    settings = load_settings(config)

    # Override from CLI arguments
    if device_id:
        settings.device.id = device_id

    logger.info("Starting Inky Display Controller")
    logger.info("Device ID: %s", settings.device.id)
    logger.info("API URL: %s", settings.api.url)
    logger.info("Mock display: %s", settings.display.mock)

    # Create controller
    controller = DisplayController(settings)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    shutdown_task: asyncio.Task[None] | None = None

    def signal_handler(sig: signal.Signals) -> None:
        nonlocal shutdown_task
        logger.info("Received signal %s, initiating shutdown...", sig.name)
        shutdown_task = loop.create_task(controller.shutdown())

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler, sig)

    _ = shutdown_task  # Reference to prevent unused variable warning

    try:
        loop.run_until_complete(controller.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        # Cancel all remaining tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()

        # Wait for cancellation
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

        loop.close()
        logger.info("Display controller stopped")


if __name__ == "__main__":
    app()
