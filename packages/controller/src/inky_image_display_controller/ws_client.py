"""WebSocket client for device communication with the API server."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import websockets
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DisplayCommand,
    RegistrationResponse,
)

logger = logging.getLogger(__name__)

CommandHandler = Callable[[DisplayCommand], Awaitable[None]]
RegistrationHandler = Callable[[RegistrationResponse], Awaitable[None]]


class WebSocketClient:
    """WebSocket client that connects to the API and handles device communication.

    Replaces the MQTT-based transport. The lifecycle is:
    1. Connect to ``ws://{api_url}/ws/devices/{device_id}``.
    2. Send ``DeviceRegistration`` JSON.
    3. First response is ``RegistrationResponse`` → call ``on_registration_response``.
    4. All subsequent messages are ``DisplayCommand`` → call ``on_command``.
    5. On disconnect: exponential backoff reconnect.
    """

    def __init__(
        self,
        api_url: str,
        device_id: str,
        on_command: CommandHandler,
        on_registration_response: RegistrationHandler,
    ) -> None:
        """Initialize the WebSocket client.

        Args:
            api_url: API base URL (e.g. ``ws://localhost:8000``).
            device_id: Device identifier for the WebSocket path.
            on_command: Callback for incoming display commands.
            on_registration_response: Callback for the registration response.

        """
        self._api_url = api_url.rstrip("/")
        self._device_id = device_id
        self._on_command = on_command
        self._on_registration_response = on_registration_response
        self._ws: websockets.ClientConnection | None = None
        self._connected = asyncio.Event()
        self._registration: str | None = None  # JSON payload set before run()

    def set_registration_payload(self, payload_json: str) -> None:
        """Store the registration JSON to send on (re-)connect.

        Args:
            payload_json: Serialised ``DeviceRegistration``.

        """
        self._registration = payload_json

    async def run(self) -> None:
        """Connect, register, and listen for commands. Auto-reconnects on failure."""
        reconnect_interval = 5
        max_reconnect_interval = 60
        ws_url = f"{self._api_url}/ws/devices/{self._device_id}"

        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    self._connected.set()
                    logger.info("Connected to API at %s", ws_url)

                    # Reset backoff on successful connection
                    reconnect_interval = 5

                    # Send registration
                    if self._registration is not None:
                        await ws.send(self._registration)
                        logger.info("Sent registration for device %s", self._device_id)

                        # First message back is the RegistrationResponse
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        response = RegistrationResponse.model_validate_json(raw)
                        await self._on_registration_response(response)

                    # Listen for commands
                    async for raw_msg in ws:
                        text = raw_msg.decode("utf-8") if isinstance(raw_msg, bytes) else raw_msg
                        try:
                            command = DisplayCommand.model_validate_json(text)
                            await self._on_command(command)
                        except Exception:
                            logger.exception("Error handling message: %s", text[:200])

            except (
                websockets.ConnectionClosed,
                OSError,
                TimeoutError,
            ) as e:
                self._connected.clear()
                self._ws = None
                logger.warning(
                    "WebSocket connection lost: %s. Reconnecting in %d seconds...",
                    e,
                    reconnect_interval,
                )
                await asyncio.sleep(reconnect_interval)
                reconnect_interval = min(reconnect_interval * 2, max_reconnect_interval)

    async def send_acknowledge(self, acknowledge: DeviceAcknowledge) -> None:
        """Send acknowledgment JSON over the WebSocket.

        Args:
            acknowledge: Acknowledgment payload.

        """
        try:
            async with asyncio.timeout(30.0):
                await self._connected.wait()
        except TimeoutError:
            raise RuntimeError("WebSocket connection timeout") from None

        if self._ws is not None:
            await self._ws.send(acknowledge.model_dump_json())
            logger.debug(
                "Sent acknowledgment: success=%s, image_id=%s",
                acknowledge.successful_display_change,
                acknowledge.image_id,
            )

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected.clear()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
