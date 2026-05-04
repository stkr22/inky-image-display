"""MQTT client used by the device controller.

Replaces the previous WebSocket transport. Subscribes to the device's
command topic, publishes acks, and announces presence via a retained
status topic with an MQTT Last-Will so the broker can publish ``offline``
on unexpected disconnects.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import aiomqtt
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceStatus,
    DisplayCommand,
)

if TYPE_CHECKING:
    from inky_image_display_controller.config import MQTTConfig

logger = logging.getLogger(__name__)

CommandHandler = Callable[[DisplayCommand], Awaitable[None]]

TOPIC_PREFIX = "inky/devices"


def _command_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/cmd"


def _ack_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/ack"


def _status_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/status"


class MQTTClient:
    """Long-running MQTT client for the controller."""

    def __init__(
        self,
        mqtt_config: MQTTConfig,
        device_id: str,
        on_command: CommandHandler,
    ) -> None:
        """Store dependencies for use by the long-running ``run()`` loop."""
        self._config = mqtt_config
        self._device_id = device_id
        self._on_command = on_command
        self._client: aiomqtt.Client | None = None
        self._connected = asyncio.Event()

    async def run(self) -> None:
        """Connect, announce ``online``, and dispatch commands forever.

        The outer loop wraps the ``aiomqtt.Client`` context manager with
        exponential backoff for unrecoverable ``MqttError``s.
        """
        backoff = self._config.reconnect_interval
        max_backoff = self._config.max_reconnect_interval
        password = self._config.password.get_secret_value() if self._config.password is not None else None

        will = aiomqtt.Will(
            topic=_status_topic(self._device_id),
            payload=DeviceStatus(status="offline").model_dump_json().encode("utf-8"),
            qos=1,
            retain=True,
        )

        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self._config.host,
                    port=self._config.port,
                    username=self._config.username,
                    password=password,
                    identifier=f"inky-controller-{self._device_id}",
                    keepalive=self._config.keep_alive,
                    tls_params=aiomqtt.TLSParameters() if self._config.tls else None,
                    transport=self._config.transport,
                    websocket_path=(self._config.websocket_path if self._config.transport == "websockets" else None),
                    will=will,
                ) as client:
                    self._client = client
                    self._connected.set()
                    backoff = self._config.reconnect_interval

                    await client.publish(
                        _status_topic(self._device_id),
                        DeviceStatus(status="online").model_dump_json(),
                        qos=1,
                        retain=True,
                    )
                    await client.subscribe(_command_topic(self._device_id), qos=1)
                    logger.info(
                        "MQTT connected to %s:%s as device %s",
                        self._config.host,
                        self._config.port,
                        self._device_id,
                    )

                    async for message in client.messages:
                        await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except aiomqtt.MqttError as exc:
                self._client = None
                self._connected.clear()
                logger.warning(
                    "MQTT connection lost: %s. Reconnecting in %ds...",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except Exception:
                self._client = None
                self._connected.clear()
                logger.exception("Unexpected MQTT failure; reconnecting in %ds", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _handle_message(self, message: aiomqtt.Message) -> None:
        payload = message.payload
        if isinstance(payload, bytes | bytearray):
            text = bytes(payload).decode("utf-8", errors="replace")
        else:
            text = str(payload)
        try:
            command = DisplayCommand.model_validate_json(text)
        except Exception:
            logger.exception("Failed to parse command: %s", text[:200])
            return
        try:
            await self._on_command(command)
        except Exception:
            logger.exception("Error handling command: %s", command.action)

    async def publish_ack(self, ack: DeviceAcknowledge) -> None:
        """Publish an acknowledgement, waiting briefly for a connection."""
        try:
            async with asyncio.timeout(30.0):
                await self._connected.wait()
        except TimeoutError:
            logger.warning("Cannot publish ack — MQTT not connected")
            return

        if self._client is None:
            return
        await self._client.publish(
            _ack_topic(self._device_id),
            ack.model_dump_json(),
            qos=1,
        )
        logger.debug(
            "Published ack: success=%s, image_id=%s",
            ack.successful_display_change,
            ack.image_id,
        )

    async def disconnect(self) -> None:
        """Publish a graceful ``offline`` status and clear connection state.

        Exiting the run-loop's context manager finalises the connection.
        """
        self._connected.clear()
        if self._client is not None:
            try:
                await self._client.publish(
                    _status_topic(self._device_id),
                    DeviceStatus(status="offline").model_dump_json(),
                    qos=1,
                    retain=True,
                )
            except Exception:
                logger.debug("Failed to publish graceful offline status", exc_info=True)
        self._client = None
