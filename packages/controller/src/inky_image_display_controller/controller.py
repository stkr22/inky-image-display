"""Main controller orchestrating all display controller components."""

import asyncio
import logging

from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DisplayCommand,
    RegistrationResponse,
)

from inky_image_display_controller.config import Settings
from inky_image_display_controller.display import (
    InkyDisplay,
    MockDisplay,
    create_display,
    profile_key_for_panel,
)
from inky_image_display_controller.exceptions import CommunicationError, DisplayError
from inky_image_display_controller.mqtt_client import MQTTClient
from inky_image_display_controller.registration import register
from inky_image_display_controller.s3_client import S3ImageClient

logger = logging.getLogger(__name__)


class DisplayController:
    """Main controller orchestrating display operations.

    Coordinates HTTP registration, MQTT command handling, S3 image
    fetching and display updates.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the display controller.

        The MQTT client is built later in ``_apply_registration_response``
        because broker connection details arrive from the API rather
        than being configured locally.
        """
        self._settings = settings
        self._current_image_id: str | None = None
        self._shutdown_event = asyncio.Event()
        # Background task that re-attempts a display command that failed, so a
        # transiently stuck panel recovers on its own. Superseded by any new
        # display/clear command and cancelled on shutdown.
        self._retry_task: asyncio.Task[None] | None = None

        self._s3 = S3ImageClient()
        self._display: InkyDisplay | MockDisplay = create_display(
            mock=settings.display.mock,
            mock_profile_key=settings.display.mock_profile_key,
        )
        self._mqtt: MQTTClient | None = None

    def _build_registration(self) -> DeviceRegistration:
        profile_key = profile_key_for_panel(self._display.width, self._display.height)
        return DeviceRegistration(
            device_id=self._settings.device.id,
            device_profile_key=profile_key,
            orientation=self._settings.display.orientation,
            room=self._settings.device.room,
        )

    async def _register_with_retry(self) -> RegistrationResponse:
        """Call the API ``/register`` endpoint, retrying transient failures.

        S3 credentials must be in hand before MQTT commands can be acted
        on, so block startup here rather than racing it against the first
        ``display`` command.
        """
        backoff = 5
        max_backoff = 60
        registration = self._build_registration()
        while not self._shutdown_event.is_set():
            try:
                return await register(self._settings.api, registration)
            except Exception as exc:
                logger.warning("Registration failed: %s. Retrying in %ds", exc, backoff)
                try:
                    async with asyncio.timeout(backoff):
                        await self._shutdown_event.wait()
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)
        raise asyncio.CancelledError("Shutdown requested during registration")

    async def run(self) -> None:
        """Register, then start MQTT and shutdown monitoring tasks."""
        logger.info("Starting display controller for device: %s", self._settings.device.id)

        try:
            response = await self._register_with_retry()
            self._apply_registration_response(response)

            assert self._mqtt is not None  # set by _apply_registration_response
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._mqtt.run(), name="mqtt")
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
        await self._shutdown_event.wait()
        raise asyncio.CancelledError("Shutdown requested")

    async def _cleanup(self) -> None:
        logger.info("Cleaning up resources...")
        self._cancel_retry()
        self._s3.close()
        if hasattr(self._display, "close"):
            self._display.close()  # ty: ignore[call-non-callable]
        if self._mqtt is not None:
            await self._mqtt.disconnect()

    def _apply_registration_response(self, response: RegistrationResponse) -> None:
        """Configure S3 and build the MQTT client from the registration response."""
        logger.info(
            "Received registration response: status=%s, s3=%s, mqtt=%s:%s",
            response.status,
            response.s3_endpoint,
            response.mqtt_host,
            response.mqtt_port,
        )
        self._s3.configure(
            endpoint=response.s3_endpoint,
            access_key=response.s3_access_key,
            secret_key=response.s3_secret_key,
            bucket=response.s3_bucket,
            secure=response.s3_secure,
            region=response.s3_region,
        )
        self._mqtt = MQTTClient(
            device_id=self._settings.device.id,
            on_command=self._handle_command,
            host=response.mqtt_host,
            port=response.mqtt_port,
            username=response.mqtt_username,
            password=response.mqtt_password,
            tls=response.mqtt_tls,
            transport=response.mqtt_transport,
            websocket_path=response.mqtt_websocket_path,
            keep_alive=response.mqtt_keep_alive,
        )

    async def _handle_command(self, command: DisplayCommand) -> None:
        """Process incoming display commands."""
        logger.info("Received command: action=%s, image_id=%s", command.action, command.image_id)

        try:
            match command.action:
                case "display":
                    # A fresh image supersedes any in-flight retry of a
                    # previously failed one — including a manual resend the
                    # operator triggered. Only commands that change what the
                    # panel shows cancel the retry; a status probe must not
                    # silently kill the device's self-recovery.
                    self._cancel_retry()
                    acked = await self._handle_display(command)
                    if not acked:
                        # The panel shows the image but the API never saw the
                        # success ack that clears its failure state — keep
                        # re-sending the ack without re-driving the panel.
                        self._schedule_retry(command, already_displayed=True)
                case "clear":
                    self._cancel_retry()
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
            # The API stops auto-rotating a device after a failed refresh; keep
            # re-attempting the same image so the device can recover unattended.
            if command.action == "display":
                self._schedule_retry(command)
        except Exception as e:
            logger.exception("Unexpected error handling command")
            await self._send_acknowledge(
                image_id=command.image_id,
                success=False,
                error=f"Unexpected error: {e}",
            )
            if command.action == "display":
                self._schedule_retry(command)

    def _cancel_retry(self) -> None:
        """Stop any pending retry loop (no-op if none is running)."""
        if self._retry_task is not None and not self._retry_task.done():
            self._retry_task.cancel()
        self._retry_task = None

    def _schedule_retry(self, command: DisplayCommand, *, already_displayed: bool = False) -> None:
        """Start a background loop that re-attempts a failed display command.

        ``already_displayed`` means the panel already shows the image and only
        the success ack failed to publish — the loop then re-sends the ack
        without re-driving the panel.
        """
        self._retry_task = asyncio.create_task(
            self._retry_loop(command, already_displayed=already_displayed), name="display_retry"
        )

    async def _retry_loop(self, command: DisplayCommand, *, already_displayed: bool = False) -> None:
        """Re-attempt ``command`` on a fixed cadence until it succeeds.

        The success ack is what clears the error server-side and lets the API
        resume auto-rotation, so the loop only ends once that ack was actually
        published — a display that succeeded while MQTT was down flips the
        loop into ack-only mode instead of ending it (re-refreshing e-paper is
        ~30 s of flashing, so the panel is not re-driven just to re-ack). Each
        failed attempt re-acks the failure to refresh the error timestamp. The
        loop is cancelled by a superseding command or by shutdown.
        """
        interval = self._settings.display.retry_interval_seconds
        displayed = already_displayed
        while not self._shutdown_event.is_set():
            try:
                async with asyncio.timeout(interval):
                    await self._shutdown_event.wait()
                return  # shutdown requested during the wait
            except TimeoutError:
                pass

            try:
                if displayed:
                    if await self._send_acknowledge(image_id=command.image_id, success=True):
                        logger.info("Republished success ack for image %s", command.image_id)
                        return
                    logger.warning("Success ack for image %s still unpublished; will retry", command.image_id)
                    continue

                logger.info("Retrying failed display for image %s", command.image_id)
                if await self._handle_display(command):
                    logger.info("Display retry succeeded for image %s", command.image_id)
                    return
                displayed = True
                logger.warning(
                    "Display retry succeeded for image %s but the success ack was not published", command.image_id
                )
            except (CommunicationError, DisplayError) as e:
                logger.warning("Display retry failed for image %s: %s", command.image_id, e)
                await self._send_acknowledge(image_id=command.image_id, success=False, error=str(e))
            except Exception as e:
                logger.exception("Unexpected error during display retry")
                await self._send_acknowledge(image_id=command.image_id, success=False, error=f"Unexpected error: {e}")

    async def _handle_display(self, command: DisplayCommand) -> bool:
        """Fetch, display and ack an image; return whether the ack published.

        A False return means the panel was updated but the API never learned
        of it — callers must arrange for the success ack to be re-sent.
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

        return await self._send_acknowledge(
            image_id=command.image_id,
            success=True,
        )

    async def _handle_clear(self) -> None:
        logger.info("Clearing display")
        await self._display.clear()
        self._current_image_id = None
        await self._send_acknowledge(success=True)

    async def _send_acknowledge(
        self,
        image_id: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> bool:
        """Publish an ack, returning whether it actually reached the broker."""
        acknowledge = DeviceAcknowledge(
            device_id=self._settings.device.id,
            image_id=image_id or self._current_image_id,
            successful_display_change=success,
            error=error,
        )

        if self._mqtt is None:
            logger.warning("Cannot publish ack — MQTT client not yet initialised")
            return False

        try:
            return await self._mqtt.publish_ack(acknowledge)
        except Exception:
            logger.exception("Failed to publish acknowledgment")
            return False
