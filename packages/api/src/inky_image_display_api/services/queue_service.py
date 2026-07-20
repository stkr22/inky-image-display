"""Grid content-queue playback.

One queue per grid replaces the former MOTD session machinery: image
groups and loose pool images are interleaved in operator order, and every
way content reaches the panels — interval rotation, the scheduled daily
display, manual "show now", release — is a step through that queue.

Playback order: never-shown entries first in ``queue_position`` order,
then the least recently shown entry cycles, so fresh content always
front-runs the replay loop. A group occupies one refresh per frame:
slot-addressed images show simultaneously (one per panel, multi-image
slots rotate), full-canvas images show one per refresh.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from inky_image_display_shared.models import Device, Grid, Image, ImageGroup
from inky_image_display_shared.schemas import DisplayCommand
from inky_image_display_shared.schemas.responses import GroupDisplayResult
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services import grid_service
from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds
from inky_image_display_api.services.image_service import next_refresh_at

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Sentinel horizon for "hold until released manually" and for parked
# single-frame holds — far enough that the rotation loop never fires.
_FAR_FUTURE = timedelta(days=3650)

# Panels released in lockstep would keep flashing simultaneously every
# interval from then on; the rejoin jitter breaks the lockstep. Capped so
# long-interval panels don't hold finished content for hours.
_RELEASE_JITTER_CAP_SECONDS = 3600


class QueueError(Exception):
    """Raised when a queue action cannot run; message is user-facing."""


def staggered_rejoin_at(interval_seconds: int, now: datetime) -> datetime:
    """Randomized rotation rejoin time after a release."""
    return now + timedelta(seconds=random.uniform(0, min(interval_seconds, _RELEASE_JITTER_CAP_SECONDS)))


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
    """Return the group's images in frame/slot order."""
    result = await session.exec(
        select(Image).where(col(Image.group_id) == group_id).order_by(col(Image.queue_position), col(Image.created_at))
    )
    return list(result.all())


def split_frames(images: list[Image]) -> tuple[dict[tuple[int, int], list[Image]], list[Image]]:
    """Partition a group into slot-addressed sequences and canvas frames."""
    slotted: dict[tuple[int, int], list[Image]] = {}
    canvas: list[Image] = []
    for image in images:
        if image.group_slot_row is not None and image.group_slot_col is not None:
            slotted.setdefault((image.group_slot_row, image.group_slot_col), []).append(image)
        else:
            canvas.append(image)
    return slotted, canvas


def frame_count(images: list[Image]) -> int:
    """Refresh frames the group occupies: slot mode rotates the longest slot."""
    slotted, canvas = split_frames(images)
    if slotted:
        return max(len(sequence) for sequence in slotted.values())
    return len(canvas)


async def _push_command(app: FastAPI, device: Device, image: Image) -> bool:
    """Push one image to a device; True when the command reached it."""
    if not app.state.mqtt.is_connected(device.device_id):
        logger.info("Device %s offline; push deferred to reconnect", device.device_id)
        return False
    command = DisplayCommand(action="display", image_path=image.storage_path, image_id=str(image.id), title=image.title)
    try:
        await app.state.mqtt.send_command(device.device_id, command)
    except Exception:
        logger.exception("Failed to push queue content to %s", device.device_id)
        return False
    return True


def _claim(device: Device, grid: Grid, image: Image, grid_next: datetime, now: datetime) -> None:
    device.claimed_by_grid_id = grid.id
    device.current_image_id = image.id
    device.displayed_since = now
    device.scheduled_next_at = grid_next
    device.updated_at = now


async def _show_group_frame(  # noqa: PLR0913 — one push spans grid, group, and transport
    app: FastAPI,
    session: AsyncSession,
    grid: Grid,
    group: ImageGroup,
    images: list[Image],
    frame: int,
    *,
    grid_next: datetime,
    now: datetime,
) -> GroupDisplayResult:
    """Push one frame of a group to the grid's panels. Does not commit."""
    slotted, canvas = split_frames(images)
    result = GroupDisplayResult(group_id=group.id, name=group.name, displayed=[], offline=[], skipped_no_content=[])
    if slotted:
        if canvas:
            logger.info("Group %s mixes slot and canvas images; canvas frames are ignored", group.id)
        targets = await grid_service.resolve_slot_targets(session, grid.id)
        for key, target in sorted(targets.items()):
            sequence = slotted.get(key)
            device = target.device
            if not sequence:
                # Slot without content — the panel keeps what it was showing.
                result.skipped_no_content.append(device.device_id)
                continue
            image = sequence[frame % len(sequence)]
            already_showing = device.current_image_id == image.id and device.claimed_by_grid_id == grid.id
            _claim(device, grid, image, grid_next, now)
            session.add(device)
            if already_showing:
                # E-ink refreshes are slow and flashy — don't repaint a
                # panel that is already showing this exact image.
                result.displayed.append(device.device_id)
                continue
            pushed = await _push_command(app, device, image)
            (result.displayed if pushed else result.offline).append(device.device_id)
        grid.current_image_id = None
    else:
        image = canvas[frame % len(canvas)]
        displayed, offline = await _push_canvas_image(app, session, grid, image, grid_next=grid_next, now=now)
        result.displayed.extend(displayed)
        result.offline.extend(offline)
    return result


async def _push_canvas_image(  # noqa: PLR0913 — explicit deps mirror the frame push
    app: FastAPI,
    session: AsyncSession,
    grid: Grid,
    image: Image,
    *,
    grid_next: datetime,
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
        _claim(device, grid, image, grid_next, now)
        session.add(device)
        crop_path = crop_paths.get(device.id)
        if crop_path is None or not app.state.mqtt.is_connected(device.device_id):
            offline.append(device.device_id)
            continue
        # Canvas pushes address the per-device crop object, not the source.
        command = DisplayCommand(action="display", image_path=crop_path, image_id=str(image.id), title=image.title)
        try:
            await app.state.mqtt.send_command(device.device_id, command)
            displayed.append(device.device_id)
        except Exception:
            logger.exception("Failed to push grid crop to %s", device.device_id)
            offline.append(device.device_id)
    grid.current_image_id = image.id
    image.last_displayed_at = now
    session.add(image)
    return displayed, offline


async def _next_playable(session: AsyncSession, grid_id: UUID) -> tuple[str, ImageGroup | Image, list[Image]] | None:
    """First queue entry that can actually show (skips empty groups)."""
    for kind, obj in await queue_entries(session, grid_id):
        if kind == "group":
            images = await group_images(session, obj.id)
            if not images:
                continue
            return kind, obj, images
        return kind, obj, []
    return None


async def advance_grid(app: FastAPI, session: AsyncSession, grid: Grid, *, force_next: bool = False) -> None:
    """Advance the grid one step; the single entry point for rotation.

    Next frame of the current group while frames remain (or a hold is
    active), otherwise the next queue entry. ``force_next`` abandons the
    current group regardless (operator release / "next"). Commits.
    """
    now = utcnow()
    default_seconds = await get_default_refresh_seconds(session, app.state.settings)
    grid_next = next_refresh_at(grid, default_seconds, now)

    if grid.current_group_id is not None:
        group = await session.get(ImageGroup, grid.current_group_id)
        images = await group_images(session, group.id) if group is not None else []
        frames = frame_count(images)
        holding = (not force_next) and grid.hold_until is not None and grid.hold_until > now
        next_frame = grid.current_frame + 1
        if group is not None and frames > 0 and not force_next and (holding or next_frame < frames):
            if frames == 1:
                # Single frame — nothing to rotate; park so the panels
                # aren't repainted every interval while the hold lasts.
                grid.scheduled_next_at = grid.hold_until or now + _FAR_FUTURE
            else:
                grid.current_frame = next_frame % frames
                await _show_group_frame(
                    app, session, grid, group, images, grid.current_frame, grid_next=grid_next, now=now
                )
                grid.scheduled_next_at = grid_next
            grid.updated_at = now
            session.add(grid)
            await session.commit()
            return
        # Group finished (or released) — record the replay timestamp.
        if group is not None:
            group.last_displayed_at = now
            session.add(group)
        grid.current_group_id = None
        grid.current_frame = 0
        grid.hold_until = None

    entry = await _next_playable(session, grid.id)
    if entry is None:
        logger.debug("Grid %s queue is empty; nothing to advance", grid.id)
        grid.updated_at = now
        session.add(grid)
        await session.commit()
        return

    kind, obj, images = entry
    if kind == "group" and isinstance(obj, ImageGroup):
        grid.current_group_id = obj.id
        grid.current_frame = 0
        await _show_group_frame(app, session, grid, obj, images, 0, grid_next=grid_next, now=now)
    elif isinstance(obj, Image):
        await _push_canvas_image(app, session, grid, obj, grid_next=grid_next, now=now)
    grid.scheduled_next_at = grid_next
    grid.updated_at = now
    session.add(grid)
    await session.commit()


async def start_group(app: FastAPI, session: AsyncSession, grid: Grid, group: ImageGroup) -> GroupDisplayResult:
    """Show a group now, front-running the queue, and hold it.

    The hold lasts ``display_duration_seconds`` (or until an explicit
    release when unset), matching the former session semantics. Commits.
    """
    now = utcnow()
    images = await group_images(session, group.id)
    if not images:
        raise QueueError("The group has no images to display")
    frames = frame_count(images)
    default_seconds = await get_default_refresh_seconds(session, app.state.settings)
    grid_next = next_refresh_at(grid, default_seconds, now)

    grid.current_group_id = group.id
    grid.current_frame = 0
    duration = grid.display_duration_seconds
    grid.hold_until = now + timedelta(seconds=duration) if duration else now + _FAR_FUTURE
    result = await _show_group_frame(app, session, grid, group, images, 0, grid_next=grid_next, now=now)
    if not result.displayed and not result.offline:
        await session.rollback()
        raise QueueError("No panel has content to display for this group")
    grid.scheduled_next_at = grid_next if frames > 1 else grid.hold_until
    grid.updated_at = now
    group.last_displayed_at = now
    session.add(grid)
    session.add(group)
    await session.commit()
    return result


async def release_queue(app: FastAPI, session: AsyncSession, grid: Grid) -> None:
    """Operator release: resume the queue immediately, jitter what follows.

    The panels update right away (the point of releasing), but the *next*
    refresh is randomized so grids released together don't flash in
    lockstep every interval from then on. With an empty queue the member
    devices are handed back to jittered solo rotation instead. Commits.
    """
    now = utcnow()
    default_seconds = await get_default_refresh_seconds(session, app.state.settings)
    grid.hold_until = None
    if await _next_playable(session, grid.id) is None:
        if grid.current_group_id is not None:
            group = await session.get(ImageGroup, grid.current_group_id)
            if group is not None:
                group.last_displayed_at = now
                session.add(group)
        grid.current_group_id = None
        grid.current_frame = 0
        devices = await session.exec(select(Device).where(col(Device.claimed_by_grid_id) == grid.id))
        for device in devices.all():
            device.claimed_by_grid_id = None
            device.scheduled_next_at = staggered_rejoin_at(device.refresh_interval_seconds or default_seconds, now)
            device.updated_at = now
            session.add(device)
        grid.updated_at = now
        session.add(grid)
        await session.commit()
        return

    await advance_grid(app, session, grid, force_next=True)
    await session.refresh(grid)
    grid.scheduled_next_at = staggered_rejoin_at(grid.refresh_interval_seconds or default_seconds, now)
    session.add(grid)
    await session.commit()


# --- Scheduled daily display ---


def _local_now(grid: Grid, now: datetime) -> datetime:
    """Lift stored naive-UTC ``now`` into the grid's display timezone."""
    return now.replace(tzinfo=UTC).astimezone(ZoneInfo(grid.display_timezone))


def _display_at_utc(grid: Grid, now: datetime) -> datetime | None:
    """Today's display time (grid-local) as naive UTC, or None off-schedule days."""
    local = _local_now(grid, now)
    if not grid.display_weekday_mask & (1 << local.weekday()):
        return None
    hour, minute = (int(piece) for piece in grid.display_time.split(":"))
    local_display = datetime.combine(local.date(), time(hour, minute), tzinfo=local.tzinfo)
    return local_display.astimezone(UTC).replace(tzinfo=None)


def local_today(grid: Grid, now: datetime) -> date:
    """Today's date on the operator's calendar (grid display timezone)."""
    return _local_now(grid, now).date()


def display_due(grid: Grid, now: datetime) -> bool:
    """Report whether the grid's scheduled daily display should start."""
    if not grid.display_schedule_enabled:
        return False
    if grid.hold_until is not None and grid.hold_until > now:
        return False
    display_at = _display_at_utc(grid, now)
    if display_at is None:
        return False
    if grid.last_displayed_on == local_today(grid, now):
        return False
    return now >= display_at


async def latest_generated_group(session: AsyncSession, grid_id: UUID) -> ImageGroup | None:
    """Return the newest worker-generated group for this grid.

    Newest wins — no per-job arbitration config.
    """
    result = await session.exec(
        select(ImageGroup)
        .where(col(ImageGroup.target_grid_id) == grid_id, col(ImageGroup.display_job_id).is_not(None))
        .order_by(col(ImageGroup.created_at).desc())
        .limit(1)
    )
    return result.first()


async def queue_tick(app: FastAPI) -> None:
    """Start due scheduled displays; called from the rotation loop."""
    now = utcnow()
    async with AsyncSession(app.state.engine) as session:
        grids_result = await session.exec(select(Grid).where(col(Grid.display_schedule_enabled).is_(True)))
        due_ids = [grid.id for grid in grids_result.all() if display_due(grid, now)]

    for grid_id in due_ids:
        async with AsyncSession(app.state.engine) as session:
            grid = await session.get(Grid, grid_id)
            if grid is None or not display_due(grid, now):
                continue
            group = await latest_generated_group(session, grid.id)
            if group is None:
                logger.debug("Grid %s scheduled display skipped — no generated group", grid.id)
                continue
            group_id = group.id
            try:
                await start_group(app, session, grid, group)
            except QueueError as exc:
                # Not marked displayed — the next tick retries until content
                # actually reaches the panels.
                logger.warning("Grid %s scheduled display could not start: %s", grid.id, exc)
                continue
            grid = await session.get(Grid, grid_id)  # start_group committed; re-fetch
            if grid is not None:
                grid.last_displayed_on = local_today(grid, now)
                session.add(grid)
                await session.commit()
            logger.info("Grid %s scheduled display started (group %s)", grid_id, group_id)
