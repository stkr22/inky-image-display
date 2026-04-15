"""Main controller orchestrating all display controller components."""

import asyncio
import logging

from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DisplayCommand,
    DisplayInfo,
    RegistrationResponse,
)

from inky_image_display_controller.config import Settings
from inky_image_display_controller.display import DisplayInterface, create_display
from inky_image_display_controller.exceptions import CommunicationError, DisplayError
from inky_image_display_controller.s3_client import S3ImageClient
from inky_image_display_controller.ws_client import WebSocketClient

logger = logging.getLogger(__name__)


class DisplayController:
    """Main controller orchestrating display operations.

    Coordinates WebSocket communication, S3 image fetching, and display updates.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the display controller.

        Args:
            settings: Application settings.

        """
        self._settings = settings
        self._current_image_id: str | None = None
        self._shutdown_event = asyncio.Event()

        # Initialize components
        self._s3 = S3ImageClient()
        self._display: DisplayInterface = create_display(
            mock=settings.display.mock,
            mock_width=settings.display.mock_width,
            mock_height=settings.display.mock_height,
        )
        self._ws = WebSocketClient(
            api_url=settings.api.url,
            device_id=settings.device.id,
            on_command=self._handle_command,
            on_registration_response=self._handle_registration_response,
        )

        # Prepare registration payload so it is sent on every (re-)connect
        registration = DeviceRegistration(
            device_id=settings.device.id,
            display=DisplayInfo(
                width=self._display.width,
                height=self._display.height,
                orientation=settings.display.orientation,
            ),
            room=settings.device.room,
        )
        self._ws.set_registration_payload(registration.model_dump_json())

    async def run(self) -> None:
        """Start all async tasks and run until shutdown.

        Runs until shutdown is requested via shutdown() method.
        """
        logger.info("Starting display controller for device: %s", self._settings.device.id)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._ws.run(), name="websocket")
                tg.create_task(self._shutdown_monitor(), name="shutdown_monitor")
        except* Exception as eg:
            for exc in eg.exceptions:
                if not isinstance(exc, asyncio.CancelledError):
                    logger.exception("Task failed: %s", exc)
        finally:
            await self._cleanup()

    async def shutdown(self) -> None:
        """Request graceful shutdown."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()

    async def _shutdown_monitor(self) -> None:
        """Monitor for shutdown signal and cancel tasks."""
        await self._shutdown_event.wait()
        raise asyncio.CancelledError("Shutdown requested")

    async def _cleanup(self) -> None:
        """Clean up resources on shutdown."""
        logger.info("Cleaning up resources...")
        self._s3.close()
        if hasattr(self._display, "close"):
            self._display.close()  # ty: ignore[call-non-callable]
        await self._ws.disconnect()

    async def _handle_registration_response(self, response: RegistrationResponse) -> None:
        """Process registration response and configure S3 client.

        Args:
            response: Registration response containing S3 credentials.

        """
        logger.info(
            "Received registration response: status=%s, endpoint=%s",
            response.status,
            response.s3_endpoint,
        )

        self._s3.configure(
            endpoint=response.s3_endpoint,
            access_key=response.s3_access_key,
            secret_key=response.s3_secret_key,
            bucket=response.s3_bucket,
            secure=response.s3_secure,
            region=response.s3_region,
        )

    async def _handle_command(self, command: DisplayCommand) -> None:
        """Process incoming display commands.

        Args:
            command: Command to process.

        """
        logger.info("Received command: action=%s, image_id=%s", command.action, command.image_id)

        try:
            match command.action:
                case "display":
                    await self._handle_display(command)
                case "clear":
                    await self._handle_clear()
                case "status":
                    await self._send_acknowledge(success=True)
                case _:
                    logger.warning("Unknown command action: %s", command.action)
                    await self._send_acknowledge(
                        image_id=command.image_id,
                        success=False,
                        error=f"Unknown action: {command.action}",
                    )
        except (CommunicationError, DisplayError) as e:
            logger.exception("Command failed: %s", command.action)
            await self._send_acknowledge(
                image_id=command.image_id,
                success=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception("Unexpected error handling command")
            await self._send_acknowledge(
                image_id=command.image_id,
                success=False,
                error=f"Unexpected error: {e}",
            )

    async def _handle_display(self, command: DisplayCommand) -> None:
        """Fetch and display an image.

        Args:
            command: Display command with image path.

        Raises:
            ValueError: If image_path or image_id is missing.
            CommunicationError: If S3 fetch fails.
            DisplayError: If display update fails.

        """
        if not command.image_path or not command.image_id:
            raise ValueError("display command requires image_path and image_id")

        if not self._s3.is_configured:
            raise CommunicationError("S3 not configured - awaiting registration")

        logger.info("Fetching image: %s", command.image_path)
        image = await self._s3.fetch_image(command.image_path)

        logger.info("Displaying image: %s", command.image_id)
        await self._display.show_image(
            image,
            saturation=self._settings.display.saturation,
        )

        self._current_image_id = command.image_id

        await self._send_acknowledge(
            image_id=command.image_id,
            success=True,
        )

    async def _handle_clear(self) -> None:
        """Clear the display.

        Raises:
            DisplayError: If display clear fails.

        """
        logger.info("Clearing display")
        await self._display.clear()
        self._current_image_id = None

        await self._send_acknowledge(success=True)

    async def _send_acknowledge(
        self,
        image_id: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Send acknowledgment after command processing.

        Args:
            image_id: Image ID if applicable.
            success: Whether the command was successful.
            error: Error message if command failed.

        """
        acknowledge = DeviceAcknowledge(
            device_id=self._settings.device.id,
            image_id=image_id or self._current_image_id,
            successful_display_change=success,
            error=error,
        )

        try:
            await self._ws.send_acknowledge(acknowledge)
        except Exception:
            logger.exception("Failed to send acknowledgment")
