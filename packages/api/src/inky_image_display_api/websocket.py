"""WebSocket endpoint for device communication."""

import logging
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from inky_image_display_shared.models import Device
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DisplayCommand,
    RegistrationResponse,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections keyed by device_id."""

    def __init__(self) -> None:
        """Initialise an empty connection registry."""
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """Accept and store a WebSocket connection.

        Args:
            device_id: Device string identifier.
            websocket: The WebSocket to store.

        """
        await websocket.accept()
        self._connections[device_id] = websocket

    def disconnect(self, device_id: str) -> None:
        """Remove a stored WebSocket connection.

        Args:
            device_id: Device string identifier.

        """
        self._connections.pop(device_id, None)

    async def send_command(self, device_id: str, command: DisplayCommand) -> None:
        """Push a display command to a connected device.

        Args:
            device_id: Target device.
            command: Command payload.

        Raises:
            KeyError: If the device is not connected.

        """
        ws = self._connections[device_id]
        await ws.send_text(command.model_dump_json())

    def is_connected(self, device_id: str) -> bool:
        """Check if a device has an active WebSocket connection."""
        return device_id in self._connections

    def connected_device_ids(self) -> list[str]:
        """Return all currently connected device IDs."""
        return list(self._connections)


async def _upsert_device(
    engine: AsyncEngine,
    device_id: str,
    registration: DeviceRegistration,
) -> Literal["registered", "updated"]:
    """Create or update a Device row and return the status string."""
    async with AsyncSession(engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()

        if device is None:
            device = Device(
                device_id=device_id,
                room=registration.room,
                display_width=registration.display.width,
                display_height=registration.display.height,
                display_orientation=registration.display.orientation,
                display_model=registration.display.model,
                is_online=True,
            )
            session.add(device)
            status: Literal["registered", "updated"] = "registered"
        else:
            device.room = registration.room
            device.display_width = registration.display.width
            device.display_height = registration.display.height
            device.display_orientation = registration.display.orientation
            device.display_model = registration.display.model
            device.is_online = True
            session.add(device)
            status = "updated"

        await session.commit()
    return status


async def _mark_device_offline(engine: AsyncEngine, device_id: str) -> None:
    """Set ``is_online=False`` for a device."""
    try:
        async with AsyncSession(engine) as session:
            result = await session.exec(select(Device).where(Device.device_id == device_id))
            device = result.first()
            if device is not None:
                device.is_online = False
                session.add(device)
                await session.commit()
    except Exception:
        logger.exception("Failed to mark device %s offline", device_id)


@router.websocket("/ws/devices/{device_id}")
async def device_websocket(websocket: WebSocket, device_id: str) -> None:
    """WebSocket endpoint replacing MQTT device communication.

    Lifecycle:
    1. Device connects.
    2. Device sends ``DeviceRegistration`` JSON.
    3. Server upserts ``Device`` row, responds with ``RegistrationResponse``.
    4. Connection stays open; server can push ``DisplayCommand`` at any time.
    5. Device sends ``DeviceAcknowledge`` after processing each command.
    6. On disconnect the device is marked offline.
    """
    app = websocket.app
    manager: ConnectionManager = app.state.connection_manager

    await manager.connect(device_id, websocket)
    logger.info("Device %s connected via WebSocket", device_id)

    try:
        # Wait for registration message
        raw = await websocket.receive_text()
        registration = DeviceRegistration.model_validate_json(raw)
        logger.info("Device %s sent registration: room=%s", device_id, registration.room)

        status = await _upsert_device(app.state.engine, device_id, registration)

        # Send registration response with S3 reader credentials
        settings = app.state.settings
        response = RegistrationResponse(
            status=status,
            s3_endpoint=settings.s3_endpoint,
            s3_bucket=settings.s3_bucket,
            s3_access_key=settings.s3_reader_access_key,
            s3_secret_key=settings.s3_reader_secret_key,
            s3_secure=settings.s3_secure,
            s3_region=settings.s3_region,
        )
        await websocket.send_text(response.model_dump_json())
        logger.info("Device %s registered (status=%s)", device_id, status)

        # Listen for acknowledgements
        while True:
            raw = await websocket.receive_text()
            try:
                ack = DeviceAcknowledge.model_validate_json(raw)
                logger.info(
                    "Device %s ack: success=%s, image_id=%s",
                    device_id,
                    ack.successful_display_change,
                    ack.image_id,
                )
            except Exception:
                logger.warning("Device %s sent unparseable message: %s", device_id, raw[:200])

    except WebSocketDisconnect:
        logger.info("Device %s disconnected", device_id)
    except Exception:
        logger.exception("WebSocket error for device %s", device_id)
    finally:
        manager.disconnect(device_id)
        await _mark_device_offline(app.state.engine, device_id)
