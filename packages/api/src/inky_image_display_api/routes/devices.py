"""REST endpoints for device management."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from inky_image_display_shared.models import Device, Image
from inky_image_display_shared.schemas import DeviceRegistration, DisplayCommand, RegistrationResponse
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.mqtt import upsert_device
from inky_image_display_api.schemas import DeviceResponse, DisplayCommandRequest, NextImageResponse
from inky_image_display_api.services.image_service import (
    build_display_command,
    get_next_image_for_device,
    update_display_state,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])
logger = logging.getLogger(__name__)


@router.post("/register")
async def register_device(request: Request, registration: DeviceRegistration) -> RegistrationResponse:
    """Upsert a device record and return the S3 reader credentials.

    Devices call this once on startup before connecting to MQTT. Online
    state is no longer set here — that arrives shortly after via the
    retained ``inky/devices/{id}/status`` topic.
    """
    settings = request.app.state.settings
    status = await upsert_device(request.app.state.engine, registration.device_id, registration)
    logger.info("Device %s registered (status=%s)", registration.device_id, status)
    return RegistrationResponse(
        status=status,
        s3_endpoint=settings.s3_endpoint,
        s3_bucket=settings.s3_bucket,
        s3_access_key=settings.s3_reader_access_key,
        s3_secret_key=settings.s3_reader_secret_key,
        s3_secure=settings.s3_secure,
        s3_region=settings.s3_region,
    )


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    request: Request,
    room: Annotated[str | None, Query(description="Filter by room name")] = None,
    is_online: Annotated[bool | None, Query(description="Filter by online status")] = None,
    id: Annotated[UUID | None, Query(description="Filter by device primary-key UUID")] = None,
) -> list[Device]:
    """List registered devices with optional filters.

    ``is_online`` reflects the broker's view of the device, kept fresh
    by retained MQTT status messages plus Last-Will-on-disconnect.
    """
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(Device)
        if room is not None:
            stmt = stmt.where(Device.room == room)
        if id is not None:
            stmt = stmt.where(col(Device.id) == id)
        if is_online is not None:
            stmt = stmt.where(Device.is_online == is_online)
        result = await session.exec(stmt)
        return list(result.all())


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(request: Request, device_id: str) -> Device:
    """Get a device by its string identifier."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return device


@router.post("/{device_id}/display")
async def send_display_command(
    request: Request,
    device_id: str,
    body: DisplayCommandRequest,
) -> dict[str, str]:
    """Send a specific image to a connected device.

    Args:
        request: Incoming HTTP request.
        device_id: Target device string identifier.
        body: Request containing the image UUID to display.

    """
    manager = request.app.state.mqtt
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    async with AsyncSession(request.app.state.engine) as session:
        # Fetch device
        dev_result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = dev_result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        # Fetch image
        img_result = await session.exec(select(Image).where(col(Image.id) == body.image_id))
        image = img_result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")

        command = build_display_command(image)
        await manager.send_command(device_id, command)
        await update_display_state(session, device, image, request.app.state.settings)

    return {"status": "ok"}


@router.post("/{device_id}/next")
async def next_image(request: Request, device_id: str) -> NextImageResponse:
    """Trigger FIFO image selection and push to device.

    Returns image metadata so callers can build responses without a second request.
    """
    manager = request.app.state.mqtt
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    async with AsyncSession(request.app.state.engine) as session:
        dev_result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = dev_result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        image = await get_next_image_for_device(session, device)
        if image is None:
            raise HTTPException(status_code=404, detail="No suitable image available")

        # Capture attributes before commit expires the instance
        response = NextImageResponse(
            status="ok",
            image_id=image.id,
            title=image.title,
            description=image.description,
            source_name=image.source_name,
            author=image.author,
        )

        command = build_display_command(image)
        await manager.send_command(device_id, command)
        await update_display_state(session, device, image, request.app.state.settings)

        return response


@router.post("/{device_id}/clear")
async def clear_device(request: Request, device_id: str) -> dict[str, str]:
    """Send a clear command to the device."""
    manager = request.app.state.mqtt
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    command = DisplayCommand(action="clear")
    await manager.send_command(device_id, command)
    return {"status": "ok"}
