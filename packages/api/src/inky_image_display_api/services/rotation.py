"""Background task for automatic content rotation and job scheduling."""

import asyncio
import logging

from fastapi import FastAPI
from inky_image_display_shared.models import Device, DisplayJob, GeminiSyncJob, ImmichSyncJob
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services import display_job_service, queue_service, sync_job_scheduling
from inky_image_display_api.services.app_settings_service import get_quiet_hours, is_quiet_now
from inky_image_display_api.services.image_service import (
    build_display_command,
    get_next_image_for_device,
    update_display_state,
)
from inky_image_display_api.services.refresh_health import dispatch_allowed_clause

logger = logging.getLogger(__name__)


async def rotation_loop(app: FastAPI) -> None:
    """Continuously drive grid schedules, solo-device rotation and job wakes.

    Runs every 30 seconds. Grids show content only via their daily display
    schedule (the queue tick, which also expires holds and hands panels
    back); solo devices rotate their FIFO pool on their refresh interval;
    job cron schedules turn into MQTT wakes for the sync worker.

    ponytail: single-replica scheduler (the chart pins replicas: 1) — needs
    a leader lock before the API can scale out.

    Args:
        app: The running FastAPI application (provides engine, settings,
             and the MQTT service via ``app.state``).

    """
    while True:
        await asyncio.sleep(30)
        try:
            await queue_service.queue_tick(app)
        except Exception:
            logger.exception("Error in scheduled-display tick")
        try:
            await wake_due_job_workers(app)
        except Exception:
            logger.exception("Error in job-wake tick")
        # Quiet hours pause only the interval-driven rotation below. The
        # queue tick above stays live because its schedule is an explicit
        # operator choice (and a hold-expiry release pushes nothing — the
        # freed panels repaint via this gated loop). Devices left overdue
        # simply rotate on the first tick after the window.
        try:
            if await _in_quiet_hours(app):
                continue
        except Exception:
            logger.exception("Error evaluating quiet hours; rotating anyway")
        try:
            await _rotate_due_devices(app)
        except Exception:
            logger.exception("Error in rotation loop")


async def wake_due_job_workers(app: FastAPI) -> None:
    """Ring the worker's doorbell for every job type with due work.

    Due-ness is decided here (the API is the scheduler); the actual
    hand-out stays with the claim endpoints, so a duplicate wake between
    two ticks is harmless — the second claim simply returns nothing.
    """
    now = utcnow()
    async with AsyncSession(app.state.engine) as session:
        checks = (
            ("immich", select(col(ImmichSyncJob.id)).where(sync_job_scheduling.due_clause(ImmichSyncJob, now))),
            ("gemini", select(col(GeminiSyncJob.id)).where(sync_job_scheduling.due_clause(GeminiSyncJob, now))),
            ("display", select(col(DisplayJob.id)).where(display_job_service.due_clause(now))),
        )
        for job_type, stmt in checks:
            if (await session.exec(stmt.limit(1))).first() is not None:
                await app.state.mqtt.publish_wake(job_type)


async def _in_quiet_hours(app: FastAPI) -> bool:
    """Whether the operator-configured quiet window is active right now."""
    async with AsyncSession(app.state.engine) as session:
        quiet_hours = await get_quiet_hours(session)
    return is_quiet_now(quiet_hours, utcnow())


async def _rotate_due_devices(app: FastAPI) -> None:
    """Find and rotate all online devices that are due for a new image.

    Devices currently claimed by a grid are skipped — the grid scheduler
    drives them instead. Devices whose last refresh failed *recently* are
    also skipped: a stuck panel keeps acking and stays "online", so without
    this gate the scheduler would keep pushing fresh images at a display
    that can't show them. The controller retries the stuck image on its
    own; once it succeeds the ack clears ``last_refresh_ok`` and the device
    re-enters rotation here. The gate expires (``dispatch_allowed_clause``)
    because that retry lives only in controller memory — after a controller
    restart or a lost success ack the failure flag would otherwise halt the
    device forever.
    """
    now = utcnow()
    async with AsyncSession(app.state.engine) as session:
        result = await session.exec(
            select(Device).where(
                Device.is_online == True,  # noqa: E712 — SQLModel comparison
                Device.scheduled_next_at <= now,
                col(Device.is_pinned).is_(False),
                col(Device.claimed_by_grid_id).is_(None),
                dispatch_allowed_clause(now, app.state.settings.refresh_error_backoff_seconds),
            )
        )
        due_devices = result.all()

    for device in due_devices:
        if not app.state.mqtt.is_connected(device.device_id):
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
        device_id = db_device.device_id
        image_id = image.id
        await app.state.mqtt.send_command(device_id, command)
        await update_display_state(session, db_device, image, app.state.settings)
        logger.info("Rotated device %s to image %s", device_id, image_id)
