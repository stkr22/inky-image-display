"""Background task for automatic image rotation."""

import asyncio
import logging
from datetime import datetime

from fastapi import FastAPI
from inky_image_display_shared.models import Device
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services.image_service import (
    build_display_command,
    get_next_image_for_device,
    update_display_state,
)

logger = logging.getLogger(__name__)


async def rotation_loop(app: FastAPI) -> None:
    """Continuously rotate images on devices whose schedule has elapsed.

    Runs every 30 seconds and checks for online devices whose
    ``scheduled_next_at`` is in the past. For each, selects the next
    image via FIFO and pushes a display command over WebSocket.

    Args:
        app: The running FastAPI application (provides engine, settings,
             and connection_manager via ``app.state``).

    """
    while True:
        await asyncio.sleep(30)
        try:
            await _rotate_due_devices(app)
        except Exception:
            logger.exception("Error in rotation loop")


async def _rotate_due_devices(app: FastAPI) -> None:
    """Find and rotate all online devices that are due for a new image."""
    now = datetime.now()
    async with AsyncSession(app.state.engine) as session:
        result = await session.exec(
            select(Device).where(
                Device.is_online == True,  # noqa: E712
                Device.scheduled_next_at <= now,
            )
        )
        due_devices = result.all()

    for device in due_devices:
        if not app.state.connection_manager.is_connected(device.device_id):
            continue
        try:
            await _rotate_single_device(app, device)
        except Exception:
            logger.exception("Failed to rotate device %s", device.device_id)


async def _rotate_single_device(app: FastAPI, device: Device) -> None:
    """Select and push the next image for a single device."""
    async with AsyncSession(app.state.engine) as session:
        result = await session.exec(select(Device).where(col(Device.id) == device.id))
        db_device = result.first()
        if db_device is None:
            return

        image = await get_next_image_for_device(session, db_device)
        if image is None:
            logger.debug("No suitable image for device %s", db_device.device_id)
            return

        command = build_display_command(image)
        await app.state.connection_manager.send_command(db_device.device_id, command)
        await update_display_state(session, db_device, image, app.state.settings)
        logger.info("Rotated device %s to image %s", db_device.device_id, image.id)
