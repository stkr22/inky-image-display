"""Message-of-the-day orchestration.

Owns the full MOTD lifecycle: generating the daily story (LLM text + AI
illustration + pre-rendered per-panel screens in S3), starting a display
session (claiming devices grid-style and pushing their first part),
rotating parts on devices with more parts than screens, expiring or
manually releasing the session, and the once-per-tick scheduler hook
called from the rotation loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

from inky_image_display_shared.ai import generate_image_bytes, generate_motd_story
from inky_image_display_shared.models import (
    Device,
    DeviceProfile,
    MotdConfig,
    MotdDeviceAssignment,
    MotdMessage,
    MotdScreen,
    PromptPreset,
)
from inky_image_display_shared.schemas import DisplayCommand
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

# Seeded preset (migration 0017) that new MOTD configs default to.
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
# all panels would keep flashing simultaneously every interval from then on.
# Release therefore staggers each device's rotation rejoin by a random offset
# within its own refresh interval, capped so long-interval panels don't hold
# the finished MOTD for hours.
_RELEASE_JITTER_CAP_SECONDS = 3600


class MotdStartError(Exception):
    """Raised when a display session cannot start; message is user-facing."""


@dataclass
class StartResult:
    """Per-device outcome of starting a session, for the API response."""

    message_id: UUID
    headline: str | None
    displayed: list[str] = field(default_factory=list)
    offline: list[str] = field(default_factory=list)
    skipped_grid_claimed: list[str] = field(default_factory=list)
    skipped_no_content: list[str] = field(default_factory=list)


def parse_parts(assignment: MotdDeviceAssignment) -> list[str]:
    """Decode the JSON-encoded ordered part list."""
    try:
        parts = json.loads(assignment.parts)
    except json.JSONDecodeError:
        return []
    return [p for p in parts if isinstance(p, str)]


async def get_or_create_config(session: AsyncSession) -> MotdConfig:
    """Return the singleton config row, creating it on first access.

    New configs start on the seeded scene preset: MOTD image subjects are
    scene descriptions, and the scene composition renders them best. The
    library-wide default preset stays the portrait one (its phrasing is the
    one that reliably passes Gemini's named-real-person checks), so the
    scene preset is looked up by name here instead.
    """
    result = await session.exec(select(MotdConfig).limit(1))
    config = result.first()
    if config is None:
        preset_result = await session.exec(select(PromptPreset).where(col(PromptPreset.name) == MOTD_SCENE_PRESET_NAME))
        scene_preset = preset_result.first()
        config = MotdConfig(image_preset_id=scene_preset.id if scene_preset else None)
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


async def list_assignments(session: AsyncSession, config_id: UUID) -> list[MotdDeviceAssignment]:
    """Return all device assignments for a config."""
    result = await session.exec(select(MotdDeviceAssignment).where(col(MotdDeviceAssignment.config_id) == config_id))
    return list(result.all())


def _local_now(config: MotdConfig, now: datetime) -> datetime:
    """Lift stored naive-UTC ``now`` into the config's timezone."""
    return now.replace(tzinfo=UTC).astimezone(ZoneInfo(config.timezone))


def _display_at_utc(config: MotdConfig, now: datetime) -> datetime | None:
    """Today's display time (config-local) as naive UTC, or None off-schedule days."""
    local = _local_now(config, now)
    if not config.weekday_mask & (1 << local.weekday()):
        return None
    hour, minute = (int(piece) for piece in config.display_time.split(":"))
    local_display = datetime.combine(local.date(), time(hour, minute), tzinfo=local.tzinfo)
    return local_display.astimezone(UTC).replace(tzinfo=None)


def _local_today(config: MotdConfig, now: datetime) -> date:
    return _local_now(config, now).date()


def generation_due(config: MotdConfig, now: datetime) -> bool:
    """Report whether the daily auto-generation should run."""
    if not config.schedule_enabled:
        return False
    display_at = _display_at_utc(config, now)
    if display_at is None:
        return False
    if config.last_generated_on == _local_today(config, now):
        return False
    return now >= display_at - timedelta(minutes=config.generation_lead_minutes)


def display_due(config: MotdConfig, now: datetime) -> bool:
    """Report whether the scheduled display should start."""
    if not config.schedule_enabled or config.active_message_id is not None:
        return False
    display_at = _display_at_utc(config, now)
    if display_at is None:
        return False
    if config.last_displayed_on == _local_today(config, now):
        return False
    return now >= display_at


async def _render_targets(
    session: AsyncSession, assignments: list[MotdDeviceAssignment]
) -> set[tuple[str, int, int, bool]]:
    """Collect the distinct (part, width, height, is_portrait) screens needed."""
    targets: set[tuple[str, int, int, bool]] = set()
    for assignment in assignments:
        dims = await _device_dims(session, assignment.device_id)
        if dims is None:
            continue
        width, height, is_portrait = dims
        for part in parse_parts(assignment):
            targets.add((part, width, height, is_portrait))
    return targets


async def _device_dims(session: AsyncSession, device_id: UUID) -> tuple[int, int, bool] | None:
    """Oriented (width, height, is_portrait) for a device, or None if missing."""
    result = await session.exec(select(Device).where(col(Device.id) == device_id))
    device = result.first()
    if device is None:
        return None
    profile_result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == device.device_profile_id))
    profile = profile_result.first()
    if profile is None:
        return None
    width, height = oriented_pixel_dims(profile, device.display_orientation)
    return width, height, device.display_orientation == "portrait"


def screen_storage_path(message_id: UUID, part: str, width: int, height: int) -> str:
    """Build the S3 object key for a rendered screen."""
    return f"motd/{message_id}/{part}_{width}x{height}.jpg"


async def generate_message(  # noqa: PLR0912, PLR0915 — sequential pipeline, splitting hurts readability
    engine: AsyncEngine,
    settings: Settings,
    s3: S3Service,
    *,
    task_id: UUID,
    tasks: GenerationTaskStore | None = None,
) -> None:
    """Generate a full MOTD message: story, illustration, rendered screens.

    Runs as a fire-and-forget background task; mirrors the error discipline
    of ``generation_service.generate_and_publish`` — errors are logged and
    recorded on the message row / task registry, never re-raised.
    """
    if settings.gemini_api_key is None:
        logger.error("MOTD generation %s aborted: GEMINI_API_KEY is not configured", task_id)
        if tasks is not None:
            await tasks.mark_failed(task_id, "GEMINI_API_KEY is not configured")
        return
    api_key = settings.gemini_api_key.get_secret_value()

    if tasks is not None:
        await tasks.mark_running(task_id)

    message_id: UUID | None = None
    try:
        async with AsyncSession(engine) as session:
            config = await get_or_create_config(session)
            # Capture scalars before the commit below expires the instance.
            config_id = config.id
            content_prompt = config.content_prompt
            grounded = config.source_mode == "grounded"
            source_mode = config.source_mode
            text_model = config.text_model_name
            image_preset_id = config.image_preset_id
            timezone_today = _local_today(config, utcnow())

            assignments = await list_assignments(session, config_id)
            targets = await _render_targets(session, assignments)
            if not targets:
                raise MotdStartError("No device assignments with content parts configured")

            message = MotdMessage(config_id=config_id, status="generating", source_mode=source_mode)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            message_id = message.id

        logger.info("MOTD generation %s: calling Gemini text model=%s grounded=%s", task_id, text_model, grounded)
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
                logger.info("MOTD generation %s: calling Gemini image model=%s", task_id, image_model)
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
                    logger.info("MOTD generation %s: part %r not renderable, skipped", task_id, part)
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
                raise MotdStartError("No screens could be rendered for this message")

            message.status = "ready"
            session.add(message)
            config_result = await session.exec(select(MotdConfig).where(col(MotdConfig.id) == config_id))
            config = config_result.one()
            config.last_generated_on = timezone_today
            session.add(config)
            await session.commit()

        await _prune_old_messages(engine, s3, config_id)
        logger.info("MOTD generation %s: message %s ready (%d screens)", task_id, message_id, rendered)
        if tasks is not None:
            await tasks.mark_completed(task_id, detail=f"Message ready with {rendered} screens")
    except Exception as exc:
        logger.exception("MOTD generation %s failed", task_id)
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


async def _prune_old_messages(engine: AsyncEngine, s3: S3Service, config_id: UUID) -> None:
    """Delete messages beyond the retention window, including S3 screens."""
    cutoff = utcnow() - timedelta(days=_RETENTION_DAYS)
    async with AsyncSession(engine) as session:
        config_result = await session.exec(select(MotdConfig).where(col(MotdConfig.id) == config_id))
        config = config_result.first()
        active_id = config.active_message_id if config else None
        result = await session.exec(
            select(MotdMessage)
            .where(col(MotdMessage.config_id) == config_id)
            .order_by(col(MotdMessage.created_at).desc())
        )
        messages = list(result.all())
        latest_ready_id = next((m.id for m in messages if m.status == "ready"), None)
        stale = [m for m in messages if m.created_at < cutoff and m.id not in (active_id, latest_ready_id)]
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


async def _latest_ready_message(session: AsyncSession, config_id: UUID) -> MotdMessage | None:
    result = await session.exec(
        select(MotdMessage)
        .where(col(MotdMessage.config_id) == config_id, col(MotdMessage.status) == "ready")
        .order_by(col(MotdMessage.created_at).desc())
        .limit(1)
    )
    return result.first()


async def screens_by_part(session: AsyncSession, message_id: UUID) -> dict[tuple[str, int, int], MotdScreen]:
    """Index a message's rendered screens by (part, width, height)."""
    result = await session.exec(select(MotdScreen).where(col(MotdScreen.message_id) == message_id))
    return {(s.part, s.width, s.height): s for s in result.all()}


async def effective_parts(
    session: AsyncSession,
    assignment: MotdDeviceAssignment,
    screens: dict[tuple[str, int, int], MotdScreen],
) -> list[MotdScreen]:
    """Return the assignment's parts that actually have a screen, in order."""
    dims = await _device_dims(session, assignment.device_id)
    if dims is None:
        return []
    width, height, _ = dims
    ordered = []
    for part in parse_parts(assignment):
        screen = screens.get((part, width, height))
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
    assignments: list[MotdDeviceAssignment],
) -> dict[tuple[str, int, int], MotdScreen]:
    """Return the message's screens, rendering any the assignments now need.

    Screens are pre-rendered at generation time from the assignments as they
    were then, so assignments edited afterwards can demand (part, panel size)
    combinations that have no screen — without this, those devices are
    silently skipped. Text and QR parts re-render from the stored story; the
    image part re-fits an existing rendered screen. Parts that still cannot
    render (image with no prior screen, QR without a source URL) stay
    missing, matching generation-time behaviour. New rows are added to the
    session and ride on the caller's commit.
    """
    screens = await screens_by_part(session, message.id)
    for part, width, height, is_portrait in sorted(await _render_targets(session, assignments)):
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


async def _claim_and_push(  # noqa: PLR0913 — claim state spans config, schedule, and transport
    session: AsyncSession,
    mqtt: MQTTService,
    device: Device,
    assignment: MotdDeviceAssignment,
    effective: list[MotdScreen],
    *,
    config_id: UUID,
    headline: str | None,
    expires_at: datetime | None,
    default_seconds: int,
    now: datetime,
) -> bool:
    """Claim the device, schedule its rotation, and push its first part.

    Returns True when the push reached the device; False when it is offline
    or the send failed (the claim stands either way — the rotation tick
    picks the device up once it reconnects).
    """
    device.claimed_by_motd_config_id = config_id
    device.displayed_since = now
    assignment.rotation_index = 0
    if len(effective) > 1:
        device.scheduled_next_at = next_refresh_at(device, default_seconds, now)
    else:
        # A single part never rotates — park the schedule so the
        # tick doesn't waste e-ink refreshes re-pushing it.
        device.scheduled_next_at = expires_at or now + _FAR_FUTURE
    device.updated_at = now
    session.add(device)
    session.add(assignment)

    screen = effective[0]
    if not mqtt.is_connected(device.device_id):
        logger.info("Device %s offline; MOTD claim set, push deferred", device.device_id)
        return False
    command = DisplayCommand(
        action="display",
        image_path=screen.storage_path,
        image_id=str(screen.id),
        title=headline,
    )
    try:
        await mqtt.send_command(device.device_id, command)
    except Exception:
        logger.exception("Failed to push MOTD to %s", device.device_id)
        return False
    return True


async def start_session(
    engine: AsyncEngine,
    mqtt: MQTTService,
    settings: Settings,
    s3: S3Service,
    message_id: UUID | None = None,
) -> StartResult:
    """Claim assigned devices and push each one's first part.

    Displays the latest ready message, or — for a redisplay from the history
    list — the explicitly requested one. Screens the current assignments
    need but the message lacks (assignments edited after generation) are
    rendered on demand first. Devices already claimed by a grid are skipped
    (existing claims win). Offline devices are claimed but receive their
    first push from the rotation tick once they reconnect.
    """
    now = utcnow()
    async with AsyncSession(engine) as session:
        config = await get_or_create_config(session)
        if message_id is not None:
            message_result = await session.exec(
                select(MotdMessage).where(
                    col(MotdMessage.id) == message_id,
                    col(MotdMessage.config_id) == config.id,
                )
            )
            message = message_result.first()
            if message is None:
                raise MotdStartError("The requested message no longer exists")
            if message.status != "ready":
                raise MotdStartError("The requested message is not ready to display")
        else:
            message = await _latest_ready_message(session, config.id)
            if message is None:
                raise MotdStartError("No generated message is ready — generate one first")
        assignments = await list_assignments(session, config.id)
        if not assignments:
            raise MotdStartError("No devices are assigned to the message of the day")

        screens = await ensure_screens(session, s3, message, assignments)
        expires_at = (
            now + timedelta(seconds=config.display_duration_seconds) if config.display_duration_seconds else None
        )
        default_seconds = await get_default_refresh_seconds(session, settings)
        result = StartResult(message_id=message.id, headline=message.headline)

        claimed_any = False
        for assignment in assignments:
            device_result = await session.exec(select(Device).where(col(Device.id) == assignment.device_id))
            device = device_result.first()
            if device is None:
                continue
            if device.claimed_by_grid_id is not None:
                result.skipped_grid_claimed.append(device.device_id)
                continue
            effective = await effective_parts(session, assignment, screens)
            if not effective:
                result.skipped_no_content.append(device.device_id)
                continue

            claimed_any = True
            pushed = await _claim_and_push(
                session,
                mqtt,
                device,
                assignment,
                effective,
                config_id=config.id,
                headline=message.headline,
                expires_at=expires_at,
                default_seconds=default_seconds,
                now=now,
            )
            (result.displayed if pushed else result.offline).append(device.device_id)

        if not claimed_any:
            await session.rollback()
            raise MotdStartError("No assigned device could be claimed")

        config.active_message_id = message.id
        config.active_since = now
        config.active_expires_at = expires_at
        config.last_displayed_on = _local_today(config, now)
        session.add(config)
        message.displayed_at = now
        session.add(message)
        await session.commit()
        return result


def _staggered_rejoin_at(device: Device, default_seconds: int, now: datetime) -> datetime:
    """Randomized rotation rejoin time for a device leaving an MOTD session."""
    interval = device.refresh_interval_seconds or default_seconds
    return now + timedelta(seconds=random.uniform(0, min(interval, _RELEASE_JITTER_CAP_SECONDS)))


async def release_session(session: AsyncSession, config: MotdConfig, settings: Settings) -> None:
    """Clear all claims and session state; devices rejoin rotation staggered."""
    now = utcnow()
    default_seconds = await get_default_refresh_seconds(session, settings)
    result = await session.exec(select(Device).where(col(Device.claimed_by_motd_config_id) == config.id))
    for device in result.all():
        device.claimed_by_motd_config_id = None
        device.scheduled_next_at = _staggered_rejoin_at(device, default_seconds, now)
        device.updated_at = now
        session.add(device)
    for assignment in await list_assignments(session, config.id):
        assignment.rotation_index = 0
        session.add(assignment)
    config.active_message_id = None
    config.active_since = None
    config.active_expires_at = None
    session.add(config)
    await session.commit()


async def resync_active_session(  # noqa: PLR0913 — session resync spans config, transport, and storage
    session: AsyncSession,
    mqtt: MQTTService,
    settings: Settings,
    s3: S3Service,
    config: MotdConfig,
    previous_parts: dict[UUID, list[str]],
) -> None:
    """Apply assignment edits to a running session; commits.

    Devices whose part list is unchanged keep their screen and schedule (no
    wasted e-ink refreshes). Changed or newly added devices get any missing
    screens rendered on demand and their first part pushed; devices removed
    from the assignments — or left with nothing renderable — are released
    back to normal rotation instead of freezing on stale content.
    """
    if config.active_message_id is None:
        return
    message_result = await session.exec(select(MotdMessage).where(col(MotdMessage.id) == config.active_message_id))
    message = message_result.first()
    if message is None:
        return

    now = utcnow()
    assignments = await list_assignments(session, config.id)
    screens = await ensure_screens(session, s3, message, assignments)
    default_seconds = await get_default_refresh_seconds(session, settings)
    config_id = config.id
    expires_at = config.active_expires_at
    headline = message.headline

    def release(device: Device) -> None:
        device.claimed_by_motd_config_id = None
        device.scheduled_next_at = now
        device.updated_at = now
        session.add(device)

    assigned_ids = {assignment.device_id for assignment in assignments}
    claimed_result = await session.exec(select(Device).where(col(Device.claimed_by_motd_config_id) == config_id))
    for device in claimed_result.all():
        if device.id not in assigned_ids:
            release(device)

    for assignment in assignments:
        if previous_parts.get(assignment.device_id) == parse_parts(assignment):
            continue
        device_result = await session.exec(select(Device).where(col(Device.id) == assignment.device_id))
        device = device_result.first()
        if device is None or device.claimed_by_grid_id is not None:
            continue
        effective = await effective_parts(session, assignment, screens)
        if not effective:
            if device.claimed_by_motd_config_id == config_id:
                release(device)
            continue
        await _claim_and_push(
            session,
            mqtt,
            device,
            assignment,
            effective,
            config_id=config_id,
            headline=headline,
            expires_at=expires_at,
            default_seconds=default_seconds,
            now=now,
        )
    await session.commit()


async def advance_due_parts(app: FastAPI) -> None:
    """Rotate each claimed, due device to its next available part."""
    now = utcnow()
    async with AsyncSession(app.state.engine) as session:
        result = await session.exec(
            select(Device).where(
                col(Device.claimed_by_motd_config_id).is_not(None),
                Device.is_online == True,  # noqa: E712 — SQLModel comparison
                Device.scheduled_next_at <= now,
                dispatch_allowed_clause(now, app.state.settings.refresh_error_backoff_seconds),
            )
        )
        due = list(result.all())
        if not due:
            return

        default_seconds = await get_default_refresh_seconds(session, app.state.settings)
        for device in due:
            try:
                await _advance_device(session, app, device, default_seconds, now)
            except Exception:
                logger.exception("Failed to advance MOTD part on %s", device.device_id)
        await session.commit()


async def _advance_device(
    session: AsyncSession,
    app: FastAPI,
    device: Device,
    default_seconds: int,
    now: datetime,
) -> None:
    config_result = await session.exec(select(MotdConfig).where(col(MotdConfig.id) == device.claimed_by_motd_config_id))
    config = config_result.first()
    if config is None or config.active_message_id is None:
        # Stale claim (config deleted or session ended unexpectedly).
        device.claimed_by_motd_config_id = None
        device.scheduled_next_at = now
        session.add(device)
        return

    assignment_result = await session.exec(
        select(MotdDeviceAssignment).where(
            col(MotdDeviceAssignment.config_id) == config.id,
            col(MotdDeviceAssignment.device_id) == device.id,
        )
    )
    assignment = assignment_result.first()
    screens = await screens_by_part(session, config.active_message_id)
    effective = await effective_parts(session, assignment, screens) if assignment else []
    if assignment is None or len(effective) <= 1:
        # Nothing to rotate — park until expiry/release.
        device.scheduled_next_at = config.active_expires_at or now + _FAR_FUTURE
        session.add(device)
        return

    if not app.state.mqtt.is_connected(device.device_id):
        return

    next_index = (assignment.rotation_index + 1) % len(effective)
    screen = effective[next_index]
    command = DisplayCommand(
        action="display",
        image_path=screen.storage_path,
        image_id=str(screen.id),
        title=None,
    )
    await app.state.mqtt.send_command(device.device_id, command)
    assignment.rotation_index = next_index
    device.scheduled_next_at = next_refresh_at(device, default_seconds, now)
    device.displayed_since = now
    device.updated_at = now
    session.add(assignment)
    session.add(device)


async def tick(app: FastAPI) -> None:
    """Scheduler hook, called from the rotation loop every ~30s.

    Order matters: expiry first (frees devices before anything else wants
    them), then generation, then the scheduled display, then part rotation.
    """
    now = utcnow()
    should_generate = False
    should_display = False
    async with AsyncSession(app.state.engine) as session:
        result = await session.exec(select(MotdConfig).limit(1))
        config = result.first()
        if config is None:
            return

        if config.active_message_id is not None and config.active_expires_at and config.active_expires_at <= now:
            logger.info("MOTD session expired; releasing devices")
            await release_session(session, config, app.state.settings)
            await session.refresh(config)

        # Evaluate schedule predicates before any further commit expires
        # the config instance (the session runs with expire_on_commit).
        config_id = config.id
        gen_candidate = generation_due(config, now) and not getattr(app.state, "motd_generation_inflight", False)
        disp_candidate = display_due(config, now)

        if gen_candidate and not await _generation_already_running(session, config_id, now):
            should_generate = True

        if disp_candidate:
            should_display = await _latest_ready_message(session, config_id) is not None

    if should_generate:
        app.state.motd_generation_inflight = True
        asyncio.create_task(_run_scheduled_generation(app, uuid4()))  # noqa: RUF006 — fire-and-forget by design

    if should_display:
        try:
            await start_session(app.state.engine, app.state.mqtt, app.state.settings, app.state.s3_service)
            logger.info("MOTD scheduled display started")
        except MotdStartError as exc:
            logger.warning("MOTD scheduled display could not start: %s", exc)

    await advance_due_parts(app)


async def _generation_already_running(session: AsyncSession, config_id: UUID, now: datetime) -> bool:
    """Report whether a fresh 'generating' row exists; stale ones are failed."""
    result = await session.exec(
        select(MotdMessage).where(
            col(MotdMessage.config_id) == config_id,
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


async def _run_scheduled_generation(app: FastAPI, task_id: UUID) -> None:
    """Run tick-spawned generation, clearing the in-flight flag afterwards."""
    try:
        tasks = getattr(app.state, "generation_tasks", None)
        if tasks is not None:
            await tasks.create(task_id, "message of the day")
        await generate_message(
            app.state.engine,
            app.state.settings,
            app.state.s3_service,
            task_id=task_id,
            tasks=tasks,
        )
    finally:
        app.state.motd_generation_inflight = False
