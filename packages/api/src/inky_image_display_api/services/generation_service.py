"""On-demand Gemini image generation orchestrated by the API service.

Background task that runs after ``POST /api/images/generate``: resolves the
prompt preset, calls Gemini, stores the result in S3, registers an Image row,
and (when ``push_immediately`` is set and the target device is online) issues
an MQTT display command so the picture shows up without polling.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from inky_image_display_shared.ai import RenderedPrompt, generate_image_bytes
from inky_image_display_shared.models import Device, DeviceProfile, Image, PromptBlock, PromptPreset
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services.image_processor import ImageProcessor
from inky_image_display_api.services.image_service import (
    build_display_command,
    update_display_state,
)
from inky_image_display_api.services.refresh_health import auto_dispatch_clause

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from inky_image_display_api.config import Settings
    from inky_image_display_api.mqtt import MQTTService
    from inky_image_display_api.services.generation_tasks import GenerationTaskStore
    from inky_image_display_api.services.s3_service import S3Service

logger = logging.getLogger(__name__)


async def resolve_preset(session: AsyncSession, preset_id: UUID | None) -> tuple[PromptPreset, dict[UUID, PromptBlock]]:
    """Load preset (defaulting to the ``is_default`` row) and its blocks."""
    if preset_id is None:
        result = await session.exec(select(PromptPreset).where(PromptPreset.is_default == True))  # noqa: E712
        preset = result.first()
        if preset is None:
            # Fall back to any preset if no default was marked.
            result = await session.exec(select(PromptPreset).limit(1))
            preset = result.first()
    else:
        result = await session.exec(select(PromptPreset).where(col(PromptPreset.id) == preset_id))
        preset = result.first()
    if preset is None:
        raise ValueError("No prompt preset available")

    block_ids = [
        preset.style_block_id,
        preset.palette_block_id,
        preset.legibility_block_id,
        preset.composition_block_id,
        preset.background_block_id,
    ]
    block_result = await session.exec(select(PromptBlock).where(col(PromptBlock.id).in_(block_ids)))
    blocks = {b.id: b for b in block_result.all()}
    missing = [bid for bid in block_ids if bid not in blocks]
    if missing:
        raise ValueError(f"Preset references missing prompt blocks: {missing}")
    return preset, blocks


def build_rendered_prompt(preset: PromptPreset, blocks: dict[UUID, PromptBlock], is_portrait: bool) -> RenderedPrompt:
    """Assemble a ``RenderedPrompt`` from a preset's five blocks."""
    return RenderedPrompt(
        style=blocks[preset.style_block_id].text,
        palette=blocks[preset.palette_block_id].text,
        legibility=blocks[preset.legibility_block_id].text,
        composition=blocks[preset.composition_block_id].text,
        background=blocks[preset.background_block_id].text,
        is_portrait=is_portrait,
    )


async def _resolve_profile(session: AsyncSession, profile_id: UUID | None) -> DeviceProfile | None:
    """Load the named profile, or fall back to the default-marked row."""
    if profile_id is not None:
        result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == profile_id))
        return result.first()
    result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.is_default).is_(True)))
    profile = result.first()
    if profile is not None:
        return profile
    # No explicit default — fall back to any seeded profile so generation still works.
    result = await session.exec(select(DeviceProfile).limit(1))
    return result.first()


def _process_and_upload(
    s3_service: S3Service,
    raw_bytes: bytes,
    width: int,
    height: int,
    storage_path: str,
) -> bool:
    """Resize the generated image to the panel and upload it; False if undecodable.

    Pillow and the MinIO SDK both block, so this runs in a worker thread as
    one unit — and under the process gate, because a full-size decode is
    the memory-heavy step the gate exists to bound.
    """
    jpeg_bytes = ImageProcessor.process_for_display(raw_bytes, width, height, upscale=True)
    if jpeg_bytes is None:
        return False
    s3_service.upload_image(storage_path, jpeg_bytes, "image/jpeg")
    return True


async def generate_and_publish(  # noqa: PLR0913
    engine: AsyncEngine,
    settings: Settings,
    s3_service: S3Service,
    mqtt: MQTTService,
    *,
    gemini_api_key: str,
    tasks: GenerationTaskStore,
    process_gate: asyncio.Semaphore,
    task_id: UUID,
    subject: str,
    target_device_profile_id: UUID | None,
    preset_id: UUID | None,
    orientation: str,
    push_immediately: bool,
) -> None:
    """Run a single on-demand generation request end to end.

    Errors are logged but not re-raised — this runs as a fire-and-forget
    background task and crashing here would not surface to the client.
    Outcomes are recorded in ``tasks`` so ``GET /api/genai/tasks`` can
    report them. The key is passed in (not read from settings) because the
    route has already refused the request when none is configured.
    """
    try:
        await tasks.mark_running(task_id)
        outcome = await _generate(
            engine,
            settings,
            s3_service,
            mqtt,
            gemini_api_key=gemini_api_key,
            process_gate=process_gate,
            task_id=task_id,
            subject=subject,
            target_device_profile_id=target_device_profile_id,
            preset_id=preset_id,
            orientation=orientation,
            push_immediately=push_immediately,
        )
    except Exception as exc:
        logger.exception("Generation task %s failed", task_id)
        await tasks.mark_failed(task_id, str(exc) or exc.__class__.__name__)
        return
    if isinstance(outcome, _Failed):
        logger.error("Generation task %s: %s", task_id, outcome.reason)
        await tasks.mark_failed(task_id, outcome.reason)
    else:
        await tasks.mark_completed(task_id, image_id=outcome.image_id, detail=outcome.detail)


@dataclass(frozen=True)
class _Failed:
    reason: str


@dataclass(frozen=True)
class _Completed:
    image_id: UUID
    detail: str


async def _generate(  # noqa: PLR0913
    engine: AsyncEngine,
    settings: Settings,
    s3_service: S3Service,
    mqtt: MQTTService,
    *,
    gemini_api_key: str,
    process_gate: asyncio.Semaphore,
    task_id: UUID,
    subject: str,
    target_device_profile_id: UUID | None,
    preset_id: UUID | None,
    orientation: str,
    push_immediately: bool,
) -> _Failed | _Completed:
    is_portrait = orientation == "portrait"
    async with AsyncSession(engine) as session:
        profile = await _resolve_profile(session, target_device_profile_id)
        if profile is None:
            return _Failed("No device profile available")
        profile_id = profile.id

        preset, blocks = await resolve_preset(session, preset_id)
        rendered = build_rendered_prompt(preset, blocks, is_portrait)
        model_name = preset.model_name

        # Profile.width/height are panel-native (landscape); swap for portrait
        # so the generated image matches the requested orientation.
        if is_portrait:
            target_width, target_height = profile.height, profile.width
        else:
            target_width, target_height = profile.width, profile.height

    logger.info("Generation task %s: calling Gemini model=%s for subject=%r", task_id, model_name, subject)
    raw_bytes = await generate_image_bytes(gemini_api_key, rendered, subject, model=model_name)

    image_uuid = uuid4()
    storage_path = f"gemini/{image_uuid}.jpg"
    async with process_gate:
        stored = await asyncio.to_thread(
            _process_and_upload, s3_service, raw_bytes, target_width, target_height, storage_path
        )
    if not stored:
        return _Failed("Image processing failed")

    async with AsyncSession(engine) as session:
        image = Image(
            id=image_uuid,
            source_name="gemini",
            source_id=str(task_id),
            storage_path=storage_path,
            title=subject,
            description=f"AI-generated: {subject}",
            tags="gemini,ai",
            original_width=target_width,
            original_height=target_height,
            is_portrait=is_portrait,
            expires_at=None,
        )
        session.add(image)
        await session.commit()
        await session.refresh(image)
        image_pk = image.id

        if not push_immediately:
            logger.info("Generation task %s: image %s registered, push skipped", task_id, image_pk)
            return _Completed(image_pk, "Image registered; push skipped")

        # Same eligibility as solo rotation: a pinned or grid-claimed panel
        # must not be overwritten, and a recently stuck one can't show it.
        now = utcnow()
        cand_result = await session.exec(
            select(Device).where(
                col(Device.device_profile_id) == profile_id,
                col(Device.display_orientation) == orientation,
                auto_dispatch_clause(now, settings.refresh_error_backoff_seconds),
            )
        )
        candidates = [d for d in cand_result.all() if mqtt.is_connected(d.device_id)]
        if not candidates:
            logger.info(
                "Generation task %s: image %s persisted but no online device matches profile %s + %s",
                task_id,
                image_pk,
                profile_id,
                orientation,
            )
            return _Completed(image_pk, "Image registered; no matching online device to push to")

        device = random.choice(candidates)
        device_mqtt_id = device.device_id
        command = build_display_command(image)
        await mqtt.send_command(device_mqtt_id, command)
        await update_display_state(session, device, image, settings)
        logger.info("Generation task %s: pushed image %s to %s", task_id, image_pk, device_mqtt_id)
        return _Completed(image_pk, f"Pushed to {device_mqtt_id}")
