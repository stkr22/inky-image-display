"""Regression tests for the on-demand Gemini generation background task."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_api.services.generation_service import generate_and_publish
from inky_image_display_shared.models import Device, Image, PromptBlock, PromptPreset
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


async def _seed_preset(engine: AsyncEngine) -> PromptPreset:
    """Insert a minimal default preset plus its five blocks."""
    async with engine.begin() as conn:
        for table in [PromptPreset.__table__, PromptBlock.__table__]:  # ty: ignore[unresolved-attribute]
            await conn.run_sync(table.create, checkfirst=True)

    blocks = [
        PromptBlock(id=uuid4(), kind=kind, name=f"{kind}-default", text=f"{kind} text", is_default=True)
        for kind in ("style", "palette", "legibility", "composition", "background")
    ]
    preset = PromptPreset(
        id=uuid4(),
        name="default",
        style_block_id=blocks[0].id,
        palette_block_id=blocks[1].id,
        legibility_block_id=blocks[2].id,
        composition_block_id=blocks[3].id,
        background_block_id=blocks[4].id,
        is_default=True,
    )
    async with AsyncSession(engine) as session:
        for block in blocks:
            session.add(block)
        session.add(preset)
        await session.commit()
    return preset


@pytest.mark.asyncio
async def test_generate_and_publish_success_path_does_not_touch_expired_attrs(  # noqa: PLR0913
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression: the trailing logger.info read expired ORM attrs → MissingGreenlet.

    We exercise the full success branch (push_immediately + mqtt.is_connected=True),
    which previously crashed when SQLAlchemy expired ``device.device_id`` and
    ``image.id`` after ``update_display_state``'s commit.
    """
    await _seed_preset(async_engine)
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    mock_settings.default_display_duration = 3600
    mock_mqtt.is_connected = MagicMock(return_value=True)

    task_id = uuid4()
    caplog.set_level("ERROR", logger="inky_image_display_api.services.generation_service")
    with patch(
        "inky_image_display_api.services.generation_service.generate_image_bytes",
        new=AsyncMock(return_value=(b"jpeg-bytes", 0.9)),
    ):
        await generate_and_publish(
            async_engine,
            mock_settings,
            mock_s3_service,
            mock_mqtt,
            task_id=task_id,
            subject="a cat",
            target_device_profile_id=seed_device.device_profile_id,
            preset_id=None,
            orientation="landscape",
            push_immediately=True,
        )

    # The background task swallows exceptions and logs them; assert nothing failed.
    failures = [r for r in caplog.records if r.levelname == "ERROR"]
    assert failures == [], f"Generation task logged errors: {[r.getMessage() for r in failures]}"
    mock_s3_service.upload_image.assert_called_once()
    mock_mqtt.send_command.assert_awaited_once()
    # An image row was persisted and the device was updated to point at it.
    async with AsyncSession(async_engine) as session:
        device_row = await session.get(Device, seed_device.id)
        assert device_row is not None
        assert device_row.current_image_id is not None
        image_row = await session.get(Image, device_row.current_image_id)
        assert image_row is not None
        assert image_row.source_name == "gemini"
