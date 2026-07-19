"""Display-job orchestration.

Two decoupled clocks drive generated content:

* The *job* generates on its own interval (LLM text + AI illustration +
  pre-rendered per-slot screens in S3), just like the sync jobs — it can
  produce content long before anything shows it.
* The *grid* owns the display schedule and session state: at its display
  time it claims its panels, pushes the latest ready message from the jobs
  targeting it (one slot part per panel), rotates multi-part slots, and
  releases the panels on expiry or manual release.

Jobs address content by grid slot (row/col of the grid layout), so the
grid remains the single claim/push mechanism — a session simply takes
over the grid's panels and hands them back when it ends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

from inky_image_display_shared.ai import generate_image_bytes, generate_motd_story
from inky_image_display_shared.models import (
    Device,
    DeviceProfile,
    DisplayJob,
    DisplayJobSlot,
    Grid,
    GridDevice,
    Image,
    MotdMessage,
    MotdScreen,
)
from inky_image_display_shared.schemas import DisplayCommand
from inky_image_display_shared.schemas.responses import DisplayJobDisplayResult
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services import motd_renderer
from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds
from inky_image_display_api.services.generation_service import build_rendered_prompt, resolve_preset
from inky_image_display_api.services.grid_service import oriented_pixel_dims
from inky_image_display_api.services.image_service import next_refresh_at
from inky_image_display_api.services.refresh_health import dispatch_allowed_clause

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

    from inky_image_display_api.config import Settings
    from inky_image_display_api.mqtt import MQTTService
    from inky_image_display_api.services.generation_tasks import GenerationTaskStore
    from inky_image_display_api.services.s3_service import S3Service

logger = logging.getLogger(__name__)

# Seeded preset (migration 0015) that new MOTD-type jobs default to.
MOTD_SCENE_PRESET_NAME = "e_ink_scene"

# Generated messages are kept for this many days so operators can redisplay
# a recent story; older ones (and their S3 screens) are pruned after each
# successful generation. The active and the newest ready message survive
# regardless of age so "Display now" keeps working after a generation gap.
_RETENTION_DAYS = 7

# A "generating" row older than this is treated as crashed (e.g. the API
# restarted mid-generation) and no longer blocks the daily auto-generation.
_GENERATING_STALE_AFTER = timedelta(minutes=15)

# Sentinel horizon for claimed devices that must not refresh again (single
# part, indefinite session). Release resets it, so it never leaks into
# normal rotation.
_FAR_FUTURE = timedelta(days=3650)

# A session pushes every panel at the same instant, and each subsequent
# refresh is scheduled relative to the previous one — released in lockstep,
# all panels (and all grids released together) would keep flashing
# simultaneously every interval from then on. Release therefore staggers
# the rotation rejoin by a random offset within the relevant refresh
# interval, capped so long-interval panels don't hold finished content for
# hours.
_RELEASE_JITTER_CAP_SECONDS = 3600


class JobStartError(Exception):
    """Raised when a display session cannot start; message is user-facing."""


def parse_parts(slot: DisplayJobSlot) -> list[str]:
    """Decode the JSON-encoded ordered part list."""
    try:
        parts = json.loads(slot.parts)
    except json.JSONDecodeError:
        return []
    return [p for p in parts if isinstance(p, str)]


async def list_jobs(session: AsyncSession) -> list[DisplayJob]:
    """Return all display jobs."""
    result = await session.exec(select(DisplayJob).order_by(col(DisplayJob.created_at)))
    return list(result.all())


async def list_slots(session: AsyncSession, job_id: UUID) -> list[DisplayJobSlot]:
    """Return all slot mappings for a job, in slot order."""
    result = await session.exec(
        select(DisplayJobSlot)
        .where(col(DisplayJobSlot.job_id) == job_id)
        .order_by(col(DisplayJobSlot.row), col(DisplayJobSlot.col))
    )
    return list(result.all())


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


def _local_today(grid: Grid, now: datetime) -> date:
    return _local_now(grid, now).date()


def generation_due(job: DisplayJob, now: datetime) -> bool:
    """Report whether the interval generation should run.

    Mirrors the sync jobs' due predicate; a job without a target grid has
    nothing to render for, so its schedule idles until it is re-targeted.
    """
    if job.interval_minutes is None or job.next_run_at is None or job.target_grid_id is None:
        return False
    return job.next_run_at <= now


def display_due(grid: Grid, now: datetime) -> bool:
    """Report whether the grid's scheduled display should start."""
    if not grid.display_schedule_enabled or grid.active_message_id is not None:
        return False
    display_at = _display_at_utc(grid, now)
    if display_at is None:
        return False
    if grid.last_displayed_on == _local_today(grid, now):
        return False
    return now >= display_at


@dataclass(frozen=True)
class SlotTarget:
    """A resolved grid slot: its device and oriented panel dimensions."""

    device: Device
    width: int
    height: int
    is_portrait: bool


async def resolve_slot_targets(session: AsyncSession, grid_id: UUID) -> dict[tuple[int, int], SlotTarget]:
    """Map each grid slot (row, col) to its device and panel dimensions."""
    placements = await session.exec(select(GridDevice).where(col(GridDevice.grid_id) == grid_id))
    targets: dict[tuple[int, int], SlotTarget] = {}
    for placement in placements.all():
        device_result = await session.exec(select(Device).where(col(Device.id) == placement.device_id))
        device = device_result.first()
        if device is None:
            continue
        profile_result = await session.exec(
            select(DeviceProfile).where(col(DeviceProfile.id) == device.device_profile_id)
        )
        profile = profile_result.first()
        if profile is None:
            continue
        width, height = oriented_pixel_dims(profile, device.display_orientation)
        targets[(placement.row, placement.col)] = SlotTarget(
            device=device,
            width=width,
            height=height,
            is_portrait=device.display_orientation == "portrait",
        )
    return targets


async def _render_targets(
    session: AsyncSession, job: DisplayJob, grid_id: UUID | None
) -> set[tuple[str, int, int, bool]]:
    """Collect the distinct (part, width, height, is_portrait) screens needed.

    ``grid_id`` is the job's target at generation time, but the *session*
    grid during display/resync — a job re-targeted mid-session keeps
    rendering for the grid it is actually showing on.
    """
    if grid_id is None:
        return set()
    slot_targets = await resolve_slot_targets(session, grid_id)
    targets: set[tuple[str, int, int, bool]] = set()
    for slot in await list_slots(session, job.id):
        target = slot_targets.get((slot.row, slot.col))
        if target is None:
            continue
        for part in parse_parts(slot):
            targets.add((part, target.width, target.height, target.is_portrait))
    return targets


def screen_storage_path(message_id: UUID, part: str, width: int, height: int) -> str:
    """Build the S3 object key for a rendered screen."""
    return f"motd/{message_id}/{part}_{width}x{height}.jpg"


async def generate_message(  # noqa: PLR0912, PLR0913, PLR0915 — sequential pipeline with explicit deps
    engine: AsyncEngine,
    settings: Settings,
    s3: S3Service,
    *,
    job_id: UUID,
    task_id: UUID,
    tasks: GenerationTaskStore | None = None,
) -> None:
    """Generate a full MOTD message for a job: story, illustration, screens.

    Runs as a fire-and-forget background task; mirrors the error discipline
    of ``generation_service.generate_and_publish`` — errors are logged and
    recorded on the message row / task registry, never re-raised.
    """
    if settings.gemini_api_key is None:
        logger.error("Display-job generation %s aborted: GEMINI_API_KEY is not configured", task_id)
        if tasks is not None:
            await tasks.mark_failed(task_id, "GEMINI_API_KEY is not configured")
        return
    api_key = settings.gemini_api_key.get_secret_value()

    if tasks is not None:
        await tasks.mark_running(task_id)

    message_id: UUID | None = None
    try:
        async with AsyncSession(engine) as session:
            job = await session.get(DisplayJob, job_id)
            if job is None:
                raise JobStartError("The display job no longer exists")
            # Capture scalars before the commit below expires the instance.
            content_prompt = job.content_prompt
            grounded = job.source_mode == "grounded"
            source_mode = job.source_mode
            text_model = job.text_model_name
            image_preset_id = job.image_preset_id

            targets = await _render_targets(session, job, job.target_grid_id)
            if not targets:
                raise JobStartError("The job has no grid slots with content parts configured")

            message = MotdMessage(job_id=job_id, status="generating", source_mode=source_mode)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            message_id = message.id

        logger.info("Job generation %s: calling Gemini text model=%s grounded=%s", task_id, text_model, grounded)
        story, source_url = await generate_motd_story(api_key, content_prompt, grounded=grounded, model=text_model)

        # One illustration per orientation actually shown; both text and
        # image prompts share the story's image_subject.
        image_orientations = {is_portrait for part, _w, _h, is_portrait in targets if part == "image"}
        ai_images: dict[bool, bytes] = {}
        if image_orientations:
            async with AsyncSession(engine) as session:
                preset, blocks = await resolve_preset(session, image_preset_id)
                image_model = preset.model_name
                prompts = {
                    is_portrait: build_rendered_prompt(preset, blocks, is_portrait)
                    for is_portrait in image_orientations
                }
            for is_portrait, prompt in prompts.items():
                logger.info("Job generation %s: calling Gemini image model=%s", task_id, image_model)
                ai_images[is_portrait] = await generate_image_bytes(
                    api_key, prompt, story.image_subject, model=image_model
                )

        async with AsyncSession(engine) as session:
            result = await session.exec(select(MotdMessage).where(col(MotdMessage.id) == message_id))
            message = result.one()
            message.headline = story.headline
            message.what = story.what
            message.why = story.why
            message.when_text = story.when_text
            message.takeaway = story.takeaway
            message.image_subject = story.image_subject
            message.source_url = source_url
            message.source_title = story.source_title

            rendered = 0
            for part, width, height, is_portrait in sorted(targets):
                screen_bytes = motd_renderer.render_part(part, message, ai_images.get(is_portrait), width, height)
                if screen_bytes is None:
                    logger.info("Job generation %s: part %r not renderable, skipped", task_id, part)
                    continue
                path = screen_storage_path(message.id, part, width, height)
                s3.upload_image(path, screen_bytes, "image/jpeg")
                session.add(
                    MotdScreen(
                        message_id=message.id,
                        part=part,
                        width=width,
                        height=height,
                        is_portrait=is_portrait,
                        storage_path=path,
                    )
                )
                rendered += 1
            if rendered == 0:
                raise JobStartError("No screens could be rendered for this message")

            message.status = "ready"
            session.add(message)
            job_result = await session.exec(select(DisplayJob).where(col(DisplayJob.id) == job_id))
            job = job_result.one()
            job.last_run_at = utcnow()
            session.add(job)
            await session.commit()

        await _prune_old_messages(engine, s3, job_id)
        logger.info("Job generation %s: message %s ready (%d screens)", task_id, message_id, rendered)
        if tasks is not None:
            await tasks.mark_completed(task_id, detail=f"Message ready with {rendered} screens")
    except Exception as exc:
        logger.exception("Display-job generation %s failed", task_id)
        error = str(exc) or exc.__class__.__name__
        if message_id is not None:
            async with AsyncSession(engine) as session:
                result = await session.exec(select(MotdMessage).where(col(MotdMessage.id) == message_id))
                message = result.first()
                if message is not None:
                    message.status = "failed"
                    message.error = error
                    session.add(message)
                    await session.commit()
        if tasks is not None:
            await tasks.mark_failed(task_id, error)


async def _prune_old_messages(engine: AsyncEngine, s3: S3Service, job_id: UUID) -> None:
    """Delete messages beyond the retention window, including S3 screens."""
    cutoff = utcnow() - timedelta(days=_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        active_result = await session.exec(
            select(Grid.active_message_id).where(col(Grid.active_message_id).is_not(None))
        )
        active_ids = set(active_result.all())
        result = await session.exec(
            select(MotdMessage).where(col(MotdMessage.job_id) == job_id).order_by(col(MotdMessage.created_at).desc())
        )
        messages = list(result.all())
        latest_ready_id = next((m.id for m in messages if m.status == "ready"), None)
        stale = [m for m in messages if m.created_at < cutoff and m.id not in active_ids and m.id != latest_ready_id]
        for message in stale:
            screens = await session.exec(select(MotdScreen).where(col(MotdScreen.message_id) == message.id))
            for screen in screens.all():
                try:
                    s3.delete_object(screen.storage_path)
                except Exception:
                    logger.warning("Failed to delete MOTD screen object %s", screen.storage_path)
                await session.delete(screen)
            await session.delete(message)
        if stale:
            await session.commit()


async def latest_ready_message(session: AsyncSession, job_id: UUID) -> MotdMessage | None:
    """Return the job's newest ready message, if any."""
    result = await session.exec(
        select(MotdMessage)
        .where(col(MotdMessage.job_id) == job_id, col(MotdMessage.status) == "ready")
        .order_by(col(MotdMessage.created_at).desc())
        .limit(1)
    )
    return result.first()


async def latest_ready_message_for_grid(session: AsyncSession, grid_id: UUID) -> MotdMessage | None:
    """Return the newest ready message across all jobs targeting this grid.

    With several jobs feeding one grid the newest content wins — the grid
    schedule needs no per-job arbitration config.
    """
    result = await session.exec(
        select(MotdMessage)
        .join(DisplayJob, col(MotdMessage.job_id) == col(DisplayJob.id))
        .where(col(DisplayJob.target_grid_id) == grid_id, col(MotdMessage.status) == "ready")
        .order_by(col(MotdMessage.created_at).desc())
        .limit(1)
    )
    return result.first()


async def screens_by_part(session: AsyncSession, message_id: UUID) -> dict[tuple[str, int, int], MotdScreen]:
    """Index a message's rendered screens by (part, width, height)."""
    result = await session.exec(select(MotdScreen).where(col(MotdScreen.message_id) == message_id))
    return {(s.part, s.width, s.height): s for s in result.all()}


def effective_screens(
    parts: list[str],
    target: SlotTarget,
    screens: dict[tuple[str, int, int], MotdScreen],
) -> list[MotdScreen]:
    """Return the slot's parts that actually have a screen, in order."""
    ordered = []
    for part in parts:
        screen = screens.get((part, target.width, target.height))
        if screen is not None:
            ordered.append(screen)
    return ordered


def _illustration_source(
    s3: S3Service,
    screens: dict[tuple[str, int, int], MotdScreen],
    is_portrait: bool,
) -> bytes | None:
    """Recover illustration bytes from an already-rendered image screen.

    The raw AI illustration is not persisted, so a panel size that needs the
    image part after generation re-fits an existing screen — same
    orientation first, to keep the cover-fit crop minimal.
    """
    candidates = sorted(
        (screen for screen in screens.values() if screen.part == "image"),
        key=lambda screen: screen.is_portrait != is_portrait,
    )
    for screen in candidates:
        try:
            return s3.get_object_bytes(screen.storage_path)
        except Exception:
            logger.warning("Could not fetch MOTD image screen %s for re-rendering", screen.storage_path)
    return None


async def ensure_screens(
    session: AsyncSession,
    s3: S3Service,
    message: MotdMessage,
    job: DisplayJob,
    grid_id: UUID,
) -> dict[tuple[str, int, int], MotdScreen]:
    """Return the message's screens, rendering any the job's slots now need.

    Screens are pre-rendered at generation time from the slot mapping as it
    was then, so slots edited afterwards can demand (part, panel size)
    combinations that have no screen — without this, those panels are
    silently skipped. Text and QR parts re-render from the stored story; the
    image part re-fits an existing rendered screen. Parts that still cannot
    render (image with no prior screen, QR without a source URL) stay
    missing, matching generation-time behaviour. New rows are added to the
    session and ride on the caller's commit.
    """
    screens = await screens_by_part(session, message.id)
    for part, width, height, is_portrait in sorted(await _render_targets(session, job, grid_id)):
        if (part, width, height) in screens:
            continue
        ai_bytes = _illustration_source(s3, screens, is_portrait) if part == "image" else None
        screen_bytes = motd_renderer.render_part(part, message, ai_bytes, width, height)
        if screen_bytes is None:
            logger.info("MOTD part %r not renderable on demand at %dx%d, skipped", part, width, height)
            continue
        path = screen_storage_path(message.id, part, width, height)
        s3.upload_image(path, screen_bytes, "image/jpeg")
        screen = MotdScreen(
            message_id=message.id,
            part=part,
            width=width,
            height=height,
            is_portrait=is_portrait,
            storage_path=path,
        )
        session.add(screen)
        screens[(part, width, height)] = screen
    return screens


async def _push_screen(mqtt: MQTTService, device: Device, screen: MotdScreen, title: str | None) -> bool:
    """Push one screen to a device; True when the command reached it."""
    if not mqtt.is_connected(device.device_id):
        logger.info("Device %s offline; job claim set, push deferred", device.device_id)
        return False
    command = DisplayCommand(
        action="display",
        image_path=screen.storage_path,
        image_id=str(screen.id),
        title=title,
    )
    try:
        await mqtt.send_command(device.device_id, command)
    except Exception:
        logger.exception("Failed to push job screen to %s", device.device_id)
        return False
    return True


def _claim_schedule(
    device: Device,
    part_count: int,
    *,
    expires_at: datetime | None,
    default_seconds: int,
    now: datetime,
) -> None:
    """Set a claimed device's next-refresh schedule for the session."""
    if part_count > 1:
        device.scheduled_next_at = next_refresh_at(device, default_seconds, now)
    else:
        # A single part never rotates — park the schedule so the tick
        # doesn't waste e-ink refreshes re-pushing it.
        device.scheduled_next_at = expires_at or now + _FAR_FUTURE


async def start_session(  # noqa: PLR0913, PLR0915 — one transaction spanning grid, slots, and transport
    engine: AsyncEngine,
    mqtt: MQTTService,
    settings: Settings,
    s3: S3Service,
    grid_id: UUID,
    message_id: UUID | None = None,
) -> DisplayJobDisplayResult:
    """Claim the grid's panels and push each slot's first part.

    Displays the latest ready message from the jobs targeting the grid, or —
    for a redisplay from the history list — the explicitly requested one.
    Screens the current slots need but the message lacks (slots edited after
    generation) are rendered on demand first. Slots without content leave
    their panel untouched. Offline devices are claimed but receive their
    first push from the rotation tick once they reconnect. Starting on a
    grid with a running session replaces that session's content.
    """
    now = utcnow()
    async with AsyncSession(engine) as session:
        grid = await session.get(Grid, grid_id)
        if grid is None:
            raise JobStartError("The grid no longer exists")

        if message_id is not None:
            message = await session.get(MotdMessage, message_id)
            if message is None:
                raise JobStartError("The requested message no longer exists")
            if message.status != "ready":
                raise JobStartError("The requested message is not ready to display")
        else:
            message = await latest_ready_message_for_grid(session, grid.id)
            if message is None:
                raise JobStartError("No generated message is ready — generate one first")

        job = await session.get(DisplayJob, message.job_id)
        if job is None:
            raise JobStartError("The display job no longer exists")

        slots = {(slot.row, slot.col): slot for slot in await list_slots(session, job.id)}
        if not slots:
            raise JobStartError("The job has no grid slots with content parts configured")

        screens = await ensure_screens(session, s3, message, job, grid.id)
        slot_targets = await resolve_slot_targets(session, grid.id)
        expires_at = now + timedelta(seconds=grid.display_duration_seconds) if grid.display_duration_seconds else None
        default_seconds = await get_default_refresh_seconds(session, settings)
        result = DisplayJobDisplayResult(
            message_id=message.id, headline=message.headline, displayed=[], offline=[], skipped_no_content=[]
        )

        claimed_any = False
        for key, target in sorted(slot_targets.items()):
            slot = slots.get(key)
            parts = parse_parts(slot) if slot else []
            device = target.device
            effective = effective_screens(parts, target, screens)
            if not effective:
                # Slot not mapped (or nothing renderable) — the panel keeps
                # whatever it was showing and stays out of the session.
                result.skipped_no_content.append(device.device_id)
                continue

            claimed_any = True
            assert slot is not None  # effective is non-empty only with a slot
            slot.rotation_index = 0
            session.add(slot)
            device.claimed_by_grid_id = grid.id
            device.displayed_since = now
            _claim_schedule(device, len(effective), expires_at=expires_at, default_seconds=default_seconds, now=now)
            device.updated_at = now
            session.add(device)
            pushed = await _push_screen(mqtt, device, effective[0], message.headline)
            (result.displayed if pushed else result.offline).append(device.device_id)

        if not claimed_any:
            await session.rollback()
            raise JobStartError("No grid slot has content to display")

        grid.active_message_id = message.id
        grid.active_since = now
        grid.active_expires_at = expires_at
        grid.last_displayed_on = _local_today(grid, now)
        grid.updated_at = now
        session.add(grid)
        message.displayed_at = now
        session.add(message)
        await session.commit()
        return result


def _staggered_rejoin_at(interval_seconds: int, now: datetime) -> datetime:
    """Randomized rotation rejoin time after a session release."""
    return now + timedelta(seconds=random.uniform(0, min(interval_seconds, _RELEASE_JITTER_CAP_SECONDS)))


async def release_session(session: AsyncSession, grid: Grid, settings: Settings) -> None:
    """End the grid's session and hand the panels back; commits.

    If the grid has an image pool, the grid resumes pool rotation (devices
    stay claimed) at a jittered time — several grids released together must
    not flash in lockstep every interval from then on. Without a pool, the
    member devices are released to solo rotation, each at its own staggered
    rejoin time for the same reason.
    """
    now = utcnow()
    default_seconds = await get_default_refresh_seconds(session, settings)

    pool_result = await session.exec(
        select(Image)
        .where(
            col(Image.target_grid_id) == grid.id,
            col(Image.excluded_from_rotation).is_(False),
        )
        .limit(1)
    )
    has_pool = pool_result.first() is not None
    if has_pool:
        interval = grid.refresh_interval_seconds or default_seconds
        grid.scheduled_next_at = _staggered_rejoin_at(interval, now)
    else:
        devices = await session.exec(select(Device).where(col(Device.claimed_by_grid_id) == grid.id))
        for device in devices.all():
            device.claimed_by_grid_id = None
            device.scheduled_next_at = _staggered_rejoin_at(device.refresh_interval_seconds or default_seconds, now)
            device.updated_at = now
            session.add(device)

    # Reset the shown job's slot rotation for the next session. The message
    # can be gone (job deleted mid-session) — then there is nothing to reset.
    if grid.active_message_id is not None:
        message = await session.get(MotdMessage, grid.active_message_id)
        if message is not None:
            for slot in await list_slots(session, message.job_id):
                slot.rotation_index = 0
                session.add(slot)
    grid.active_message_id = None
    grid.active_since = None
    grid.active_expires_at = None
    grid.updated_at = now
    session.add(grid)
    await session.commit()


async def resync_active_session(  # noqa: PLR0913 — session resync spans job, transport, and storage
    session: AsyncSession,
    mqtt: MQTTService,
    settings: Settings,
    s3: S3Service,
    job: DisplayJob,
    previous_parts: dict[tuple[int, int], list[str]],
) -> None:
    """Apply slot edits to any session currently showing this job; commits.

    Slots whose part list is unchanged keep their screen and schedule (no
    wasted e-ink refreshes). Changed or newly mapped slots get any missing
    screens rendered on demand and their first part pushed; slots removed
    from the mapping — or left with nothing renderable — release their
    panel back to rotation instead of freezing on stale content.
    """
    message_ids = select(col(MotdMessage.id)).where(col(MotdMessage.job_id) == job.id)
    grid_result = await session.exec(select(Grid).where(col(Grid.active_message_id).in_(message_ids)))
    grid = grid_result.first()
    if grid is None or grid.active_message_id is None:
        return
    message = await session.get(MotdMessage, grid.active_message_id)
    if message is None:
        return

    now = utcnow()
    screens = await ensure_screens(session, s3, message, job, grid.id)
    slot_targets = await resolve_slot_targets(session, grid.id)
    slots = {(slot.row, slot.col): slot for slot in await list_slots(session, job.id)}
    default_seconds = await get_default_refresh_seconds(session, settings)
    expires_at = grid.active_expires_at
    grid_id = grid.id

    for key, target in sorted(slot_targets.items()):
        slot = slots.get(key)
        parts = parse_parts(slot) if slot else []
        if previous_parts.get(key, []) == parts:
            continue
        device = target.device
        effective = effective_screens(parts, target, screens)
        if not effective:
            if device.claimed_by_grid_id == grid_id:
                device.claimed_by_grid_id = None
                device.scheduled_next_at = _staggered_rejoin_at(device.refresh_interval_seconds or default_seconds, now)
                device.updated_at = now
                session.add(device)
            continue
        if slot is not None:
            slot.rotation_index = 0
            session.add(slot)
        device.claimed_by_grid_id = grid_id
        device.displayed_since = now
        _claim_schedule(device, len(effective), expires_at=expires_at, default_seconds=default_seconds, now=now)
        device.updated_at = now
        session.add(device)
        await _push_screen(mqtt, device, effective[0], message.headline)
    await session.commit()


async def advance_due_slots(app: FastAPI) -> None:
    """Rotate each active session's due multi-part slots to their next part."""
    now = utcnow()
    async with AsyncSession(app.state.engine) as session:
        grids_result = await session.exec(select(Grid).where(col(Grid.active_message_id).is_not(None)))
        grids = list(grids_result.all())
        if not grids:
            return
        default_seconds = await get_default_refresh_seconds(session, app.state.settings)
        for grid in grids:
            try:
                await _advance_grid_slots(session, app, grid, default_seconds, now)
            except Exception:
                logger.exception("Failed to advance display-job slots on grid %s", grid.id)
        await session.commit()


async def _advance_grid_slots(
    session: AsyncSession,
    app: FastAPI,
    grid: Grid,
    default_seconds: int,
    now: datetime,
) -> None:
    if grid.active_message_id is None:
        return
    message = await session.get(MotdMessage, grid.active_message_id)
    if message is None:
        return
    due_result = await session.exec(
        select(Device).where(
            col(Device.claimed_by_grid_id) == grid.id,
            Device.is_online == True,  # noqa: E712 — SQLModel comparison
            Device.scheduled_next_at <= now,
            dispatch_allowed_clause(now, app.state.settings.refresh_error_backoff_seconds),
        )
    )
    due_devices = {device.id: device for device in due_result.all()}
    if not due_devices:
        return

    screens = await screens_by_part(session, message.id)
    slot_targets = await resolve_slot_targets(session, grid.id)
    slots = {(slot.row, slot.col): slot for slot in await list_slots(session, message.job_id)}

    for key, target in slot_targets.items():
        device = due_devices.get(target.device.id)
        if device is None:
            continue
        slot = slots.get(key)
        effective = effective_screens(parse_parts(slot), target, screens) if slot else []
        if slot is None or len(effective) <= 1:
            # Nothing to rotate — park until expiry/release.
            device.scheduled_next_at = grid.active_expires_at or now + _FAR_FUTURE
            session.add(device)
            continue
        if not app.state.mqtt.is_connected(device.device_id):
            continue

        next_index = (slot.rotation_index + 1) % len(effective)
        if not await _push_screen(app.state.mqtt, device, effective[next_index], None):
            continue
        slot.rotation_index = next_index
        device.scheduled_next_at = next_refresh_at(device, default_seconds, now)
        device.displayed_since = now
        device.updated_at = now
        session.add(slot)
        session.add(device)


def _inflight_jobs(app: FastAPI) -> set[UUID]:
    inflight = getattr(app.state, "display_job_generation_inflight", None)
    if inflight is None:
        inflight = set()
        app.state.display_job_generation_inflight = inflight
    return inflight


async def tick(app: FastAPI) -> None:
    """Scheduler hook, called from the rotation loop every ~30s.

    Order matters: session expiry first (frees the grid before anything
    else wants it), then interval generation, then the grids' scheduled
    displays, then part rotation across all active sessions.
    """
    now = utcnow()
    to_generate: list[UUID] = []
    to_display: list[UUID] = []
    async with AsyncSession(app.state.engine) as session:
        expired_result = await session.exec(
            select(Grid).where(col(Grid.active_message_id).is_not(None), col(Grid.active_expires_at) <= now)
        )
        for grid in expired_result.all():
            logger.info("Display session on grid %s expired; releasing panels", grid.id)
            await release_session(session, grid, app.state.settings)

        for job in await list_jobs(session):
            if (
                generation_due(job, now)
                and job.id not in _inflight_jobs(app)
                and not await _generation_already_running(session, job.id, now)
            ):
                # Advancing the schedule at spawn doubles as a lease, exactly
                # like the sync jobs' claim — a slow generation must not be
                # started again by the next tick.
                assert job.interval_minutes is not None  # implied by generation_due
                job.next_run_at = now + timedelta(minutes=job.interval_minutes)
                session.add(job)
                to_generate.append(job.id)
        await session.commit()

        grids_result = await session.exec(select(Grid).where(col(Grid.display_schedule_enabled).is_(True)))
        for grid in grids_result.all():
            if display_due(grid, now) and await latest_ready_message_for_grid(session, grid.id) is not None:
                to_display.append(grid.id)

    for job_id in to_generate:
        _inflight_jobs(app).add(job_id)
        asyncio.create_task(_run_scheduled_generation(app, job_id, uuid4()))  # noqa: RUF006 — fire-and-forget by design

    for grid_id in to_display:
        try:
            await start_session(app.state.engine, app.state.mqtt, app.state.settings, app.state.s3_service, grid_id)
            logger.info("Grid %s scheduled display started", grid_id)
        except JobStartError as exc:
            logger.warning("Grid %s scheduled display could not start: %s", grid_id, exc)

    await advance_due_slots(app)


async def _generation_already_running(session: AsyncSession, job_id: UUID, now: datetime) -> bool:
    """Report whether a fresh 'generating' row exists; stale ones are failed."""
    result = await session.exec(
        select(MotdMessage).where(
            col(MotdMessage.job_id) == job_id,
            col(MotdMessage.status) == "generating",
        )
    )
    running = False
    for message in result.all():
        if message.created_at > now - _GENERATING_STALE_AFTER:
            running = True
        else:
            message.status = "failed"
            message.error = "Generation did not finish (process restarted?)"
            session.add(message)
    await session.commit()
    return running


async def _run_scheduled_generation(app: FastAPI, job_id: UUID, task_id: UUID) -> None:
    """Run tick-spawned generation, clearing the in-flight flag afterwards."""
    try:
        tasks = getattr(app.state, "generation_tasks", None)
        if tasks is not None:
            await tasks.create(task_id, "message of the day")
        await generate_message(
            app.state.engine,
            app.state.settings,
            app.state.s3_service,
            job_id=job_id,
            task_id=task_id,
            tasks=tasks,
        )
    finally:
        _inflight_jobs(app).discard(job_id)
