"""MQTT transport between the API and connected devices.

Replaces the previous WebSocket transport. The broker handles connection
state, keepalive and Last-Will-and-Testament announcements, so the API
only has to react to status messages and keep an in-memory set of devices
currently considered online.

Topic layout (single-level wildcards used for subscriptions):

* ``inky/devices/{id}/status`` — retained, device → broker, ``DeviceStatus``.
* ``inky/devices/{id}/cmd``    — API → device, ``DisplayCommand``.
* ``inky/devices/{id}/ack``    — device → API, ``DeviceAcknowledge``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

import aiomqtt
from fastapi import HTTPException, status
from inky_image_display_shared.models import Device, DeviceProfile
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DeviceStatus,
    DisplayCommand,
)
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from inky_image_display_api.config import Settings

logger = logging.getLogger(__name__)


TOPIC_PREFIX = "inky/devices"


def _command_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/cmd"


def _status_filter() -> str:
    return f"{TOPIC_PREFIX}/+/status"


def _ack_filter() -> str:
    return f"{TOPIC_PREFIX}/+/ack"


_TOPIC_MIN_PARTS = 4


def _device_id_from_topic(topic: str) -> str | None:
    """Extract ``{device_id}`` from ``inky/devices/{device_id}/<suffix>``."""
    parts = topic.split("/")
    if len(parts) < _TOPIC_MIN_PARTS or parts[0] != "inky" or parts[1] != "devices":
        return None
    return parts[2]


async def upsert_device(
    engine: AsyncEngine,
    device_id: str,
    registration: DeviceRegistration,
) -> Literal["registered", "updated"]:
    """Create or update a Device row; used by the HTTP /register endpoint."""
    async with AsyncSession(engine) as session:
        profile_result = await session.exec(
            select(DeviceProfile).where(DeviceProfile.key == registration.device_profile_key)
        )
        profile = profile_result.first()
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown device_profile_key '{registration.device_profile_key}'",
            )

        result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        now = datetime.now()

        if device is None:
            device = Device(
                device_id=device_id,
                room=registration.room,
                device_profile_id=profile.id,
                display_orientation=registration.orientation,
                is_online=False,  # Becomes True once we see the MQTT online status.
                last_seen=now,
            )
            session.add(device)
            outcome: Literal["registered", "updated"] = "registered"
        else:
            device.room = registration.room
            device.device_profile_id = profile.id
            device.display_orientation = registration.orientation
            device.last_seen = now
            session.add(device)
            outcome = "updated"

        await session.commit()
    return outcome


async def _touch_last_seen(engine: AsyncEngine, device_id: str) -> None:
    """Bump ``last_seen`` and ``is_online`` on any inbound message.

    This keeps the freshness-based online indicator self-healing even
    if a stale event raced ahead and flipped ``is_online`` to False.
    """
    try:
        async with AsyncSession(engine) as session:
            result = await session.exec(select(Device).where(Device.device_id == device_id))
            device = result.first()
            if device is not None:
                device.last_seen = datetime.now()
                device.is_online = True
                session.add(device)
                await session.commit()
    except Exception:
        logger.exception("Failed to touch last_seen for device %s", device_id)


async def _set_online_flag(engine: AsyncEngine, device_id: str, *, online: bool) -> None:
    """Update only the ``is_online`` flag (used by status messages)."""
    try:
        async with AsyncSession(engine) as session:
            result = await session.exec(select(Device).where(Device.device_id == device_id))
            device = result.first()
            if device is not None:
                device.is_online = online
                if online:
                    device.last_seen = datetime.now()
                session.add(device)
                await session.commit()
    except Exception:
        logger.exception("Failed to update online flag for device %s", device_id)


class MQTTService:
    """Long-running MQTT client used by the API.

    Subscribes to status and ack topics, maintains an in-memory set of
    online device ids, and exposes ``send_command`` to publish
    ``DisplayCommand`` payloads to a specific device.
    """

    def __init__(self, settings: Settings, engine: AsyncEngine) -> None:
        """Store dependencies and initialise the empty online registry."""
        self._settings = settings
        self._engine = engine
        self._client: aiomqtt.Client | None = None
        self._client_ready = asyncio.Event()
        self._online: set[str] = set()

    @property
    def online_devices(self) -> set[str]:
        """Return the set of devices currently considered online."""
        return self._online

    def is_connected(self, device_id: str) -> bool:
        """Return whether the broker has reported the device as online."""
        return device_id in self._online

    def connected_device_ids(self) -> list[str]:
        """Return all currently online device ids as a list."""
        return list(self._online)

    async def send_command(self, device_id: str, command: DisplayCommand) -> None:
        """Publish a command to ``inky/devices/{id}/cmd`` at QoS 1.

        Raises:
            KeyError: If the device is not currently online.
            RuntimeError: If the MQTT client is not connected to the broker.

        """
        if device_id not in self._online:
            raise KeyError(device_id)
        if self._client is None:
            raise RuntimeError("MQTT client is not connected")
        await self._client.publish(
            _command_topic(device_id),
            command.model_dump_json(),
            qos=1,
        )

    async def run(self) -> None:
        """Connect to the broker and dispatch messages forever.

        The outer loop wraps the ``aiomqtt.Client`` context manager so the
        service recovers from unrecoverable ``MqttError``s with exponential
        backoff. Transient drops are handled inside aiomqtt itself.
        """
        backoff = 5
        max_backoff = 60
        password = self._settings.mqtt_password.get_secret_value() if self._settings.mqtt_password is not None else None

        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self._settings.mqtt_host,
                    port=self._settings.mqtt_port,
                    username=self._settings.mqtt_username,
                    password=password,
                    identifier=self._settings.mqtt_client_id,
                    keepalive=self._settings.mqtt_keep_alive,
                    tls_params=aiomqtt.TLSParameters() if self._settings.mqtt_tls else None,
                    transport=self._settings.mqtt_transport,
                    websocket_path=(
                        self._settings.mqtt_websocket_path if self._settings.mqtt_transport == "websockets" else None
                    ),
                ) as client:
                    self._client = client
                    self._client_ready.set()
                    backoff = 5

                    await client.subscribe(_status_filter(), qos=1)
                    await client.subscribe(_ack_filter(), qos=1)
                    logger.info(
                        "MQTT connected to %s:%s, subscribed to status and ack topics",
                        self._settings.mqtt_host,
                        self._settings.mqtt_port,
                    )

                    async for message in client.messages:
                        await self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except aiomqtt.MqttError as exc:
                self._client = None
                self._client_ready.clear()
                self._online.clear()
                logger.warning(
                    "MQTT connection lost: %s. Reconnecting in %ds...",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except Exception:
                self._client = None
                self._client_ready.clear()
                self._online.clear()
                logger.exception("Unexpected MQTT failure; reconnecting in %ds", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _dispatch(self, message: aiomqtt.Message) -> None:
        topic = str(message.topic)
        device_id = _device_id_from_topic(topic)
        if device_id is None:
            logger.debug("Ignoring message on unexpected topic: %s", topic)
            return

        payload = message.payload
        if isinstance(payload, bytes | bytearray):
            text = bytes(payload).decode("utf-8", errors="replace")
        else:
            text = str(payload)

        if topic.endswith("/status"):
            await self._handle_status(device_id, text)
        elif topic.endswith("/ack"):
            await self._handle_ack(device_id, text)
        else:
            logger.debug("Ignoring message on unexpected topic: %s", topic)

    async def _handle_status(self, device_id: str, text: str) -> None:
        try:
            status = DeviceStatus.model_validate_json(text)
        except Exception:
            logger.warning("Device %s sent unparseable status: %s", device_id, text[:200])
            return

        if status.status == "online":
            self._online.add(device_id)
            await _set_online_flag(self._engine, device_id, online=True)
            logger.info("Device %s is online", device_id)
        else:
            self._online.discard(device_id)
            await _set_online_flag(self._engine, device_id, online=False)
            logger.info("Device %s is offline", device_id)

    async def _handle_ack(self, device_id: str, text: str) -> None:
        try:
            ack = DeviceAcknowledge.model_validate_json(text)
        except Exception:
            logger.warning("Device %s sent unparseable ack: %s", device_id, text[:200])
            return

        logger.info(
            "Device %s ack: success=%s, image_id=%s",
            device_id,
            ack.successful_display_change,
            ack.image_id,
        )
        # Acks count as proof-of-life — keep the device marked online.
        self._online.add(device_id)
        await _touch_last_seen(self._engine, device_id)
