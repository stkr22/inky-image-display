"""Grid content-queue playback.

One queue per grid: image groups and loose pool images are interleaved
in operator order. A grid shows content only when told to — by its daily
display schedule (which steps the queue one entry forward), or by an
operator action ("show now" / "next"). There is no interval rotation for
grids: every display holds until ``display_duration_seconds`` elapses
(or an explicit release when unset), and then the member panels return
to their own solo rotation.

Playback order: never-shown entries first in ``queue_position`` order,
then the least recently shown entry cycles, so fresh content always
front-runs the replay loop. A group is a frozen panel spread — exactly
one image per slot, shown simultaneously. Loose pool images cover-crop
across the whole grid.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from inky_image_display_shared.models import Device, Grid, Image, ImageGroup
from inky_image_display_shared.schemas import DisplayCommand
from inky_image_display_shared.schemas.responses import GroupDisplayResult
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services import grid_service
from inky_image_display_api.services.sync_job_scheduling import next_cron_run

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class QueueError(Exception):
    """Raised when a queue action cannot run; message is user-facing."""


async def queue_entries(session: AsyncSession, grid_id: UUID) -> list[tuple[str, ImageGroup | Image]]:
    """Return the grid's queue in predicted playback order.

    Fresh (never-shown) entries first in operator ``queue_position`` order,
    then shown entries by least recently displayed — "if there is nothing
    new, start over with the least recent".

    ponytail: reordering only affects entries that have not been shown yet;
    once everything cycled the replay order is pure LRU. Add an explicit
    cursor if operators need reorder to bite mid-cycle.
    """
    groups = await session.exec(select(ImageGroup).where(col(ImageGroup.target_grid_id) == grid_id))
    images = await session.exec(
        select(Image).where(
            col(Image.target_grid_id) == grid_id,
            col(Image.group_id).is_(None),
            col(Image.excluded_from_rotation).is_(False),
        )
    )
    entries: list[tuple[str, ImageGroup | Image]] = [("group", g) for g in groups.all()]
    entries.extend(("image", i) for i in images.all())

    def sort_key(entry: tuple[str, ImageGroup | Image]) -> tuple[bool, int, datetime, datetime]:
        obj = entry[1]
        shown = obj.last_displayed_at is not None
        return (shown, 0 if shown else obj.queue_position, obj.last_displayed_at or datetime.min, obj.created_at)

    return sorted(entries, key=sort_key)


async def group_images(session: AsyncSession, group_id: UUID) -> list[Image]:
    """Return the group's images in slot order."""
    result = await session.exec(
        select(Image).where(col(Image.group_id) == group_id).order_by(col(Image.queue_position), col(Image.created_at))
    )
    return list(result.all())


def slot_images(images: list[Image]) -> dict[tuple[int, int], Image]:
    """Map a spread's images to their panel slot — one image per slot.

    A group is a frozen spread; extra images in the same slot are a data
    error (logged, first wins). Images without a slot assignment are not
    shown — operators assign panels in the Groups overview; the worker
    always sets slots.
    """
    slotted: dict[tuple[int, int], Image] = {}
    for image in images:
        if image.group_slot_row is None or image.group_slot_col is None:
            logger.debug("Image %s in group %s has no panel assignment; not shown", image.id, image.group_id)
            continue
        key = (image.group_slot_row, image.group_slot_col)
        if key in slotted:
            logger.warning("Group %s has multiple images in slot %s; showing the first", image.group_id, key)
            continue
        slotted[key] = image
    return slotted


async def _push_command(app: FastAPI, device: Device, image: Image) -> bool:
    """Push one image to a device; True when the command reached it."""
    if not app.state.mqtt.is_connected(device.device_id):
        logger.info("Device %s offline; push deferred to reconnect", device.device_id)
        return False
    command = DisplayCommand(action="display", image_path=image.storage_path, image_id=str(image.id))
    try:
        await app.state.mqtt.send_command(device.device_id, command)
    except Exception:
        logger.exception("Failed to push queue content to %s", device.device_id)
        return False
    return True


def _claim(device: Device, grid: Grid, image: Image, now: datetime) -> None:
    # While claimed the device's own ``scheduled_next_at`` is inert (solo
    # rotation skips claimed devices); release makes it due immediately.
    device.claimed_by_grid_id = grid.id
    device.current_image_id = image.id
    device.displayed_since = now
    device.updated_at = now


async def _show_group(  # noqa: PLR0913 — one push spans grid, group, and transport
    app: FastAPI,
    session: AsyncSession,
    grid: Grid,
    group: ImageGroup,
    images: list[Image],
    *,
    now: datetime,
) -> GroupDisplayResult:
    """Push a group spread to the grid's panels. Does not commit."""
    slotted = slot_images(images)
    result = GroupDisplayResult(group_id=group.id, name=group.name, displayed=[], offline=[], skipped_no_content=[])
    targets = await grid_service.resolve_slot_targets(session, grid.id)
    for key, target in sorted(targets.items()):
        image = slotted.get(key)
        device = target.device
        if image is None:
            # Slot without content — the panel keeps what it was showing.
            result.skipped_no_content.append(device.device_id)
            continue
        already_showing = device.current_image_id == image.id and device.claimed_by_grid_id == grid.id
        _claim(device, grid, image, now)
        session.add(device)
        if already_showing:
            # E-ink refreshes are slow and flashy — don't repaint a
            # panel that is already showing this exact image.
            result.displayed.append(device.device_id)
            continue
        pushed = await _push_command(app, device, image)
        (result.displayed if pushed else result.offline).append(device.device_id)
    grid.current_image_id = None
    grid.current_group_id = group.id
    grid.displayed_since = now
    group.last_displayed_at = now
    session.add(group)
    return result


async def _push_canvas_image(
    app: FastAPI,
    session: AsyncSession,
    grid: Grid,
    image: Image,
    *,
    now: datetime,
) -> tuple[list[str], list[str]]:
    """Push one image cover-cropped across every panel. No commit."""
    crop_paths = await grid_service.render_and_upload(session, grid, image, app.state.s3_service)
    placements = await grid_service.list_grid_devices(session, grid.id)
    displayed: list[str] = []
    offline: list[str] = []
    for placement in placements:
        device = await grid_service.get_device_or_404(session, placement.device_id)
        if device.claimed_by_grid_id is not None and device.claimed_by_grid_id != grid.id:
            logger.warning("Device %s held by another grid; skipped", device.device_id)
            continue
        _claim(device, grid, image, now)
        session.add(device)
        crop_path = crop_paths.get(device.id)
        if crop_path is None or not app.state.mqtt.is_connected(device.device_id):
            offline.append(device.device_id)
            continue
        # Canvas pushes address the per-device crop object, not the source.
        command = DisplayCommand(action="display", image_path=crop_path, image_id=str(image.id))
        try:
            await app.state.mqtt.send_command(device.device_id, command)
            displayed.append(device.device_id)
        except Exception:
            logger.exception("Failed to push grid crop to %s", device.device_id)
            offline.append(device.device_id)
    grid.current_group_id = None
    grid.current_image_id = image.id
    grid.displayed_since = now
    image.last_displayed_at = now
    session.add(image)
    return displayed, offline


async def _next_playable(session: AsyncSession, grid_id: UUID) -> tuple[str, ImageGroup | Image, list[Image]] | None:
    """First queue entry that can actually show (skips groups with no panel assignments)."""
    for kind, obj in await queue_entries(session, grid_id):
        if kind == "group":
            images = await group_images(session, obj.id)
            if not slot_images(images):
                continue
            return kind, obj, images
        return kind, obj, []
    return None


async def show_next(app: FastAPI, session: AsyncSession, grid: Grid) -> bool:
    """Show the next queue entry and hold it; the queue's only step function.

    Returns False (without touching the panels) when the queue has no
    playable entry. Commits on success.
    """
    entry = await _next_playable(session, grid.id)
    if entry is None:
        logger.debug("Grid %s queue is empty; nothing to show", grid.id)
        return False

    now = utcnow()
    kind, obj, images = entry
    if kind == "group" and isinstance(obj, ImageGroup):
        await _show_group(app, session, grid, obj, images, now=now)
    elif isinstance(obj, Image):
        await _push_canvas_image(app, session, grid, obj, now=now)
    grid.hold_until = grid_service.hold_horizon(grid, now)
    grid.updated_at = now
    session.add(grid)
    await session.commit()
    return True


async def start_group(app: FastAPI, session: AsyncSession, grid: Grid, group: ImageGroup) -> GroupDisplayResult:
    """Show a specific group now, front-running the queue, and hold it. Commits."""
    now = utcnow()
    images = await group_images(session, group.id)
    if not slot_images(images):
        raise QueueError("The group has no panel assignments")

    result = await _show_group(app, session, grid, group, images, now=now)
    if not result.displayed and not result.offline:
        await session.rollback()
        raise QueueError("No panel has content to display for this group")
    grid.hold_until = grid_service.hold_horizon(grid, now)
    grid.updated_at = now
    session.add(grid)
    await session.commit()
    return result


async def release_queue(session: AsyncSession, grid: Grid) -> None:
    """End the grid's display and hand the panels back to solo rotation.

    Runs on hold expiry and on operator release alike. Every panel is due
    immediately, so the next rotation tick repaints them all at once; that
    mass rotation then staggers each panel's *following* refresh (see
    ``rotation._rotate_due_devices``) so they don't keep flashing in
    lockstep every interval. Commits.
    """
    now = utcnow()
    grid.current_group_id = None
    grid.current_image_id = None
    grid.hold_until = None
    devices = await session.exec(select(Device).where(col(Device.claimed_by_grid_id) == grid.id))
    for device in devices.all():
        device.claimed_by_grid_id = None
        device.scheduled_next_at = now
        device.updated_at = now
        session.add(device)
    grid.updated_at = now
    session.add(grid)
    await session.commit()


# --- Scheduled display ---


def display_due(grid: Grid, now: datetime) -> bool:
    """Report whether the grid's scheduled display should start.

    ``display_next_at`` is a lease exactly like the jobs' ``next_run_at``:
    it is stamped by the grid routes when the schedule is edited/enabled
    and advanced along the cron grid by ``queue_tick`` once a display
    actually starts.
    """
    if not grid.display_schedule_enabled or grid.display_next_at is None:
        return False
    if grid.hold_until is not None and grid.hold_until > now:
        return False
    return now >= grid.display_next_at


async def queue_tick(app: FastAPI) -> None:
    """Expire holds and start due scheduled displays; runs from the rotation loop."""
    now = utcnow()
    # expire_on_commit=False: release_queue commits per grid, and the next
    # loop iteration still reads the already-loaded grid rows.
    async with AsyncSession(app.state.engine, expire_on_commit=False) as session:
        expired = await session.exec(select(Grid).where(col(Grid.hold_until).is_not(None), col(Grid.hold_until) <= now))
        for grid in expired.all():
            await release_queue(session, grid)
            logger.info("Grid %s display ended; panels returned to solo rotation", grid.id)

    async with AsyncSession(app.state.engine) as session:
        grids_result = await session.exec(select(Grid).where(col(Grid.display_schedule_enabled).is_(True)))
        due_ids = [grid.id for grid in grids_result.all() if display_due(grid, now)]

    for grid_id in due_ids:
        async with AsyncSession(app.state.engine) as session:
            grid = await session.get(Grid, grid_id)
            if grid is None or not display_due(grid, now):
                continue
            # An empty queue does not advance the lease — the next tick
            # retries until content (e.g. the day's generated group) exists.
            if not await show_next(app, session, grid):
                continue
            grid = await session.get(Grid, grid_id)  # show_next committed; re-fetch
            if grid is not None:
                grid.display_next_at = next_cron_run(grid.display_cron, grid.display_timezone, now)
                session.add(grid)
                await session.commit()
            logger.info("Grid %s scheduled display started", grid_id)
