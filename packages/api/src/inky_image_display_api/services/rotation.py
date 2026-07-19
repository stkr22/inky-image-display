"""Background task for automatic image rotation."""

import asyncio
import logging

from fastapi import FastAPI
from inky_image_display_shared.models import Device, Grid
from inky_image_display_shared.time import utcnow
from sqlalchemy import not_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services import display_job_service, grid_service
from inky_image_display_api.services.app_settings_service import get_quiet_hours, is_quiet_now
from inky_image_display_api.services.image_service import (
    build_display_command,
    get_next_image_for_device,
    update_display_state,
)
from inky_image_display_api.services.refresh_health import dispatch_allowed_clause

logger = logging.getLogger(__name__)


async def rotation_loop(app: FastAPI) -> None:
    """Continuously rotate images on devices whose schedule has elapsed.

    Runs every 30 seconds and checks for online devices whose
    ``scheduled_next_at`` is in the past. For each, selects the next
    image via FIFO and publishes a display command over MQTT.

    Args:
        app: The running FastAPI application (provides engine, settings,
             and the MQTT service via ``app.state``).

    """
    while True:
        await asyncio.sleep(30)
        try:
            await display_job_service.tick(app)
        except Exception:
            logger.exception("Error in display-job tick")
        # Quiet hours pause only the interval-driven rotation below. The
        # display-job tick above stays live because its schedule is an
        # explicit operator choice; manual pushes bypass this loop entirely.
        # Devices left overdue simply rotate on the first tick after the
        # window.
        try:
            if await _in_quiet_hours(app):
                continue
        except Exception:
            logger.exception("Error evaluating quiet hours; rotating anyway")
        try:
            await _rotate_due_grids(app)
        except Exception:
            logger.exception("Error in grid rotation tick")
        try:
            await _rotate_due_devices(app)
        except Exception:
            logger.exception("Error in rotation loop")


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


async def _rotate_due_grids(app: FastAPI) -> None:
    """Advance any grid whose schedule has elapsed."""
    now = utcnow()
    async with AsyncSession(app.state.engine) as session:
        result = await session.exec(select(Grid).where(Grid.scheduled_next_at <= now))
        due_grids = list(result.all())

    for grid in due_grids:
        try:
            await _rotate_single_grid(app, grid.id)
        except Exception:
            logger.exception("Failed to rotate grid %s", grid.id)


async def _rotate_single_grid(app: FastAPI, grid_id: object) -> None:
    """Pick the next image for a grid and push slices to every member device."""
    async with AsyncSession(app.state.engine) as session:
        grid = await session.exec(select(Grid).where(col(Grid.id) == grid_id))
        db_grid = grid.first()
        if db_grid is None:
            return
        # Empty grids are valid state (created in the UI before the user
        # adds devices), so the background tick treats them like grids
        # without images: log at debug and move on. ``render_and_upload``
        # still raises 400 when called from the explicit route, which is
        # the correct behaviour for a user-driven request.
        placements = await grid_service.list_grid_devices(session, db_grid.id)
        if not placements:
            logger.debug("No devices placed on grid %s", db_grid.id)
            return
        # A grid renders one image in lockstep across every member, so a
        # single stuck panel makes the whole composite unshowable. Pause
        # the grid until that member recovers (its controller retries the
        # stuck image and the success ack clears last_refresh_ok) — or
        # until the failure ages past the dispatch backoff, so a member
        # whose controller restarted can't pause the grid forever.
        member_ids = [p.device_id for p in placements]
        errored = await session.exec(
            select(Device.device_id).where(
                col(Device.id).in_(member_ids),
                not_(dispatch_allowed_clause(utcnow(), app.state.settings.refresh_error_backoff_seconds)),
            )
        )
        stuck = errored.all()
        if stuck:
            logger.debug("Grid %s paused — member(s) %s have a failed refresh", db_grid.id, ", ".join(stuck))
            return
        # A display job holding this grid drives the panels exclusively;
        # pool rotation resumes when the session releases the grid.
        if await display_job_service.has_active_session(session, db_grid.id):
            logger.debug("Grid %s paused — a display job session is active", db_grid.id)
            return
        image = await grid_service.get_next_grid_image(session, db_grid)
        if image is None:
            logger.debug("No images assigned to grid %s", db_grid.id)
            return
        crop_paths = await grid_service.render_and_upload(session, db_grid, image, app.state.s3_service)
        # Capture ids before claim_devices_and_push commits: the commit
        # expires both instances and re-reading them here would lazy-load
        # outside the async greenlet (MissingGreenlet).
        rotated_image_id = image.id
        await grid_service.claim_devices_and_push(
            session,
            db_grid,
            image,
            crop_paths,
            app.state.mqtt,
            app.state.settings,
        )
        logger.info("Rotated grid %s to image %s", grid_id, rotated_image_id)
