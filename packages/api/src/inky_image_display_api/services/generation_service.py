"""On-demand Gemini image generation orchestrated by the API service.

Background task that runs after ``POST /api/images/generate``: resolves the
prompt preset, calls Gemini, stores the result in S3, registers an Image row,
and (when ``push_immediately`` is set and the target device is online) issues
an MQTT display command so the picture shows up without polling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from inky_image_display_shared.ai import RenderedPrompt, generate_image_bytes
from inky_image_display_shared.models import Device, Image, PromptBlock, PromptPreset
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services.image_service import (
    build_display_command,
    update_display_state,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from inky_image_display_api.config import Settings
    from inky_image_display_api.mqtt import MQTTService
    from inky_image_display_api.services.s3_service import S3Service

logger = logging.getLogger(__name__)


async def _resolve_preset(
    session: AsyncSession, preset_id: UUID | None
) -> tuple[PromptPreset, dict[UUID, PromptBlock]]:
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


def _build_rendered_prompt(preset: PromptPreset, blocks: dict[UUID, PromptBlock], is_portrait: bool) -> RenderedPrompt:
    return RenderedPrompt(
        style=blocks[preset.style_block_id].text,
        palette=blocks[preset.palette_block_id].text,
        legibility=blocks[preset.legibility_block_id].text,
        composition=blocks[preset.composition_block_id].text,
        background=blocks[preset.background_block_id].text,
        is_portrait=is_portrait,
    )


async def generate_and_publish(  # noqa: PLR0913
    engine: AsyncEngine,
    settings: Settings,
    s3_service: S3Service,
    mqtt: MQTTService,
    *,
    task_id: UUID,
    subject: str,
    target_device_id: UUID,
    preset_id: UUID | None,
    is_portrait: bool,
    push_immediately: bool,
) -> None:
    """Run a single on-demand generation request end to end.

    Errors are logged but not re-raised — this runs as a fire-and-forget
    background task and crashing here would not surface to the client.
    """
    if settings.gemini_api_key is None:
        logger.error("Generation task %s aborted: GEMINI_API_KEY is not configured", task_id)
        return

    try:
        async with AsyncSession(engine) as session:
            dev_result = await session.exec(select(Device).where(col(Device.id) == target_device_id))
            device = dev_result.first()
            if device is None:
                logger.error("Generation task %s: device %s not found", task_id, target_device_id)
                return

            preset, blocks = await _resolve_preset(session, preset_id)
            rendered = _build_rendered_prompt(preset, blocks, is_portrait)
            model_name = preset.model_name

            # The device's display dims are stored landscape-native; swap for
            # portrait so the generated image matches the orientation flag.
            if is_portrait:
                target_width, target_height = device.display_height, device.display_width
            else:
                target_width, target_height = device.display_width, device.display_height

        logger.info("Generation task %s: calling Gemini model=%s for subject=%r", task_id, model_name, subject)
        jpeg_bytes, score = await generate_image_bytes(
            settings.gemini_api_key.get_secret_value(),
            rendered,
            subject,
            target_width,
            target_height,
            model=model_name,
        )
        logger.info("Generation task %s: Spectra-6 score %.3f", task_id, score)

        image_uuid = uuid4()
        storage_path = f"gemini/{image_uuid}.jpg"
        s3_service.upload_image(storage_path, jpeg_bytes, "image/jpeg")

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

            if not push_immediately:
                logger.info("Generation task %s: image %s registered, push skipped", task_id, image.id)
                return

            dev_result = await session.exec(select(Device).where(col(Device.id) == target_device_id))
            device = dev_result.first()
            if device is None:
                return
            if not mqtt.is_connected(device.device_id):
                logger.info(
                    "Generation task %s: device %s offline, image %s waits for next rotation",
                    task_id,
                    device.device_id,
                    image.id,
                )
                # Surface the new image to the next rotation by clearing the
                # scheduled-next timestamp so it fires immediately on reconnect.
                device.scheduled_next_at = datetime.now()
                session.add(device)
                await session.commit()
                return

            command = build_display_command(image)
            # Snapshot identifiers before update_display_state's commit expires the ORM instances.
            device_mqtt_id = device.device_id
            image_pk = image.id
            await mqtt.send_command(device_mqtt_id, command)
            await update_display_state(session, device, image, settings)
            logger.info("Generation task %s: pushed image %s to %s", task_id, image_pk, device_mqtt_id)
    except Exception:
        logger.exception("Generation task %s failed", task_id)


def schedule_retention_cleanup_window(settings: Settings) -> timedelta:
    """Default retention window for on-demand images (unused placeholder).

    Reserved for a future feature; on-demand images currently never expire
    automatically.
    """
    del settings
    return timedelta(days=0)
