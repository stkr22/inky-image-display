"""Tests for MOTD orchestration: generation, sessions, rotation, release."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_api.services import motd_service
from inky_image_display_api.services.motd_service import (
    MotdStartError,
    advance_due_parts,
    display_due,
    generate_message,
    generation_due,
    get_or_create_config,
    release_session,
    start_session,
)
from inky_image_display_api.services.rotation import _rotate_due_devices
from inky_image_display_shared.ai import MotdStory
from inky_image_display_shared.models import (
    Device,
    MotdConfig,
    MotdDeviceAssignment,
    MotdMessage,
    MotdScreen,
    PromptPreset,
)
from inky_image_display_shared.time import utcnow
from PIL import Image
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

STORY = MotdStory(
    headline="Village builds its own bridge",
    what="A village crowdfunded and built a footbridge.",
    why="It reconnects two communities split by a river.",
    when_text="Last week",
    takeaway="Small groups can fix big gaps.",
    image_subject="A wooden footbridge over a calm river at sunrise.",
    source_title="Example News",
)


async def _seed_config_with_assignment(
    engine: AsyncEngine,
    device: Device,
    parts: list[str],
) -> MotdConfig:
    async with AsyncSession(engine) as session:
        config = await get_or_create_config(session)
        session.add(MotdDeviceAssignment(config_id=config.id, device_id=device.id, parts=json.dumps(parts)))
        await session.commit()
        await session.refresh(config)
    return config


async def _seed_ready_message(
    engine: AsyncEngine, config: MotdConfig, parts: list[str], dims: tuple[int, int]
) -> MotdMessage:
    width, height = dims
    async with AsyncSession(engine) as session:
        message = MotdMessage(
            config_id=config.id,
            status="ready",
            headline=STORY.headline,
            what=STORY.what,
            why=STORY.why,
            when_text=STORY.when_text,
            takeaway=STORY.takeaway,
            source_url="https://news.example/bridge",
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        for part in parts:
            session.add(
                MotdScreen(
                    message_id=message.id,
                    part=part,
                    width=width,
                    height=height,
                    is_portrait=False,
                    storage_path=f"motd/{message.id}/{part}_{width}x{height}.jpg",
                )
            )
        await session.commit()
        await session.refresh(message)
    return message


@pytest.mark.asyncio
async def test_generate_message_renders_screens_per_assignment(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Full generation path: story + screens for the assigned parts/dims."""
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    await _seed_config_with_assignment(async_engine, seed_device, ["what", "why+takeaway", "qr"])

    with patch(
        "inky_image_display_api.services.motd_service.generate_motd_story",
        new=AsyncMock(return_value=(STORY, "https://news.example/bridge")),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, task_id=uuid4())

    async with AsyncSession(async_engine) as session:
        message = (await session.exec(select(MotdMessage))).one()
        assert message.status == "ready"
        assert message.what == STORY.what
        assert message.source_url == "https://news.example/bridge"
        screens = (await session.exec(select(MotdScreen))).all()
        # seed_device is a landscape 1600x1200 panel.
        assert {(s.part, s.width, s.height) for s in screens} == {
            ("what", 1600, 1200),
            ("why+takeaway", 1600, 1200),
            ("qr", 1600, 1200),
        }
        config = (await session.exec(select(MotdConfig))).one()
        assert config.last_generated_on is not None
    assert mock_s3_service.upload_image.call_count == 3


@pytest.mark.asyncio
async def test_generate_message_without_source_url_skips_qr(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    await _seed_config_with_assignment(async_engine, seed_device, ["what", "qr"])

    with patch(
        "inky_image_display_api.services.motd_service.generate_motd_story",
        new=AsyncMock(return_value=(STORY, None)),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, task_id=uuid4())

    async with AsyncSession(async_engine) as session:
        screens = (await session.exec(select(MotdScreen))).all()
        assert [s.part for s in screens] == ["what"]


@pytest.mark.asyncio
async def test_generate_message_generates_image_once_per_orientation(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    await _seed_config_with_assignment(async_engine, seed_device, ["image"])

    fake_image = AsyncMock(return_value=_tiny_jpeg())
    fake_preset = MagicMock(model_name="gemini-image")
    with (
        patch(
            "inky_image_display_api.services.motd_service.generate_motd_story",
            new=AsyncMock(return_value=(STORY, None)),
        ),
        patch(
            "inky_image_display_api.services.motd_service.resolve_preset",
            new=AsyncMock(return_value=(fake_preset, {})),
        ),
        patch(
            "inky_image_display_api.services.motd_service.build_rendered_prompt",
            return_value=MagicMock(),
        ),
        patch("inky_image_display_api.services.motd_service.generate_image_bytes", new=fake_image),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, task_id=uuid4())

    assert fake_image.await_count == 1
    async with AsyncSession(async_engine) as session:
        screens = (await session.exec(select(MotdScreen))).all()
        assert [s.part for s in screens] == ["image"]


@pytest.mark.asyncio
async def test_generate_message_records_failure(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    await _seed_config_with_assignment(async_engine, seed_device, ["what"])

    with patch(
        "inky_image_display_api.services.motd_service.generate_motd_story",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, task_id=uuid4())

    async with AsyncSession(async_engine) as session:
        message = (await session.exec(select(MotdMessage))).one()
        assert message.status == "failed"
        assert message.error == "boom"


@pytest.mark.asyncio
async def test_start_session_claims_and_pushes(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what", "why"])
    await _seed_ready_message(async_engine, config, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings)

    assert result.displayed == [seed_device.device_id]
    command = mock_mqtt.send_command.await_args.args[1]
    assert command.image_path.endswith("what_1600x1200.jpg")
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_motd_config_id == config.id
        db_config = (await session.exec(select(MotdConfig))).one()
        assert db_config.active_message_id is not None
        assert db_config.active_expires_at is None  # default duration = indefinite


@pytest.mark.asyncio
async def test_start_session_skips_grid_claimed_device(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        device.claimed_by_grid_id = uuid4()
        session.add(device)
        await session.commit()

    with pytest.raises(MotdStartError, match="could be claimed"):
        await start_session(async_engine, mock_mqtt, mock_settings)


@pytest.mark.asyncio
async def test_start_session_without_message_raises(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    with pytest.raises(MotdStartError, match="No generated message"):
        await start_session(async_engine, mock_mqtt, mock_settings)


def _make_app(engine: AsyncEngine, settings: MagicMock, mqtt: MagicMock) -> MagicMock:
    app = MagicMock()
    app.state.engine = engine
    app.state.settings = settings
    app.state.mqtt = mqtt
    app.state.motd_generation_inflight = False
    app.state.generation_tasks = None
    return app


@pytest.mark.asyncio
async def test_advance_rotates_and_wraps(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    """A due, claimed device advances through its parts and wraps around."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what", "why"])
    await _seed_ready_message(async_engine, config, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings)

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    for expected_part in ("why", "what"):
        async with AsyncSession(async_engine) as session:
            device = (await session.exec(select(Device))).one()
            device.scheduled_next_at = utcnow() - timedelta(seconds=1)
            session.add(device)
            await session.commit()
        await advance_due_parts(app)
        command = mock_mqtt.send_command.await_args.args[1]
        assert f"{expected_part}_1600x1200" in command.image_path

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.scheduled_next_at > utcnow()


@pytest.mark.asyncio
async def test_advance_parks_single_part_device(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    """Single-part devices are parked, not re-pushed every interval."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings)
    assert mock_mqtt.send_command.await_count == 1

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        device.scheduled_next_at = utcnow() - timedelta(seconds=1)
        session.add(device)
        await session.commit()
    await advance_due_parts(app)
    assert mock_mqtt.send_command.await_count == 1  # no extra e-ink refresh


@pytest.mark.asyncio
async def test_release_returns_devices_to_rotation(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings)

    before = utcnow()
    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        await release_session(session, db_config)

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_motd_config_id is None
        assert device.scheduled_next_at <= utcnow()
        assert device.scheduled_next_at >= before - timedelta(seconds=1)
        db_config = (await session.exec(select(MotdConfig))).one()
        assert db_config.active_message_id is None
        assignment = (await session.exec(select(MotdDeviceAssignment))).one()
        assert assignment.rotation_index == 0


@pytest.mark.asyncio
async def test_expired_session_is_released_by_tick(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        db_config.display_duration_seconds = 60
        session.add(db_config)
        await session.commit()
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings)

    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        assert db_config.active_expires_at is not None
        db_config.active_expires_at = utcnow() - timedelta(seconds=1)
        session.add(db_config)
        await session.commit()

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    await motd_service.tick(app)

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_motd_config_id is None
        db_config = (await session.exec(select(MotdConfig))).one()
        assert db_config.active_message_id is None


def test_schedule_due_helpers() -> None:
    """Weekday mask, lead time and once-per-day guards drive the tick."""
    config = MotdConfig(
        schedule_enabled=True,
        display_time="08:00",
        weekday_mask=127,
        timezone="UTC",
        generation_lead_minutes=60,
    )
    before_lead = datetime(2026, 7, 1, 6, 30)
    within_lead = datetime(2026, 7, 1, 7, 30)
    after_display = datetime(2026, 7, 1, 8, 5)

    assert not generation_due(config, before_lead)
    assert generation_due(config, within_lead)
    assert not display_due(config, within_lead)
    assert display_due(config, after_display)

    config.last_generated_on = within_lead.date()
    assert not generation_due(config, within_lead)
    config.last_displayed_on = after_display.date()
    assert not display_due(config, after_display)

    # Wednesday 2026-07-01; mask without Wednesday (bit 2) → nothing fires.
    config.last_generated_on = None
    config.last_displayed_on = None
    config.weekday_mask = 127 & ~(1 << 2)
    assert not generation_due(config, within_lead)
    assert not display_due(config, after_display)


def test_schedule_respects_timezone() -> None:
    """08:00 in Berlin (UTC+2 in July) is 06:00 UTC."""
    config = MotdConfig(
        schedule_enabled=True,
        display_time="08:00",
        weekday_mask=127,
        timezone="Europe/Berlin",
        generation_lead_minutes=0,
    )
    assert not display_due(config, datetime(2026, 7, 1, 5, 55))
    assert display_due(config, datetime(2026, 7, 1, 6, 5))


def _tiny_jpeg() -> bytes:
    out = BytesIO()
    Image.new("RGB", (64, 48), "#446688").save(out, format="JPEG")
    return out.getvalue()


@pytest.mark.asyncio
async def test_new_config_defaults_to_scene_preset(async_engine: AsyncEngine) -> None:
    """A lazily-created config picks the seeded scene preset when present."""
    block_id = uuid4()
    async with AsyncSession(async_engine) as session:
        session.add(
            PromptPreset(
                id=uuid4(),
                name="e_ink_scene",
                style_block_id=block_id,
                palette_block_id=block_id,
                legibility_block_id=block_id,
                composition_block_id=block_id,
                background_block_id=block_id,
                is_default=False,
            )
        )
        await session.commit()

    async with AsyncSession(async_engine) as session:
        config = await get_or_create_config(session)
        preset = (await session.exec(select(PromptPreset))).one()
        assert config.image_preset_id == preset.id


@pytest.mark.asyncio
async def test_new_config_without_scene_preset_falls_back_to_none(async_engine: AsyncEngine) -> None:
    async with AsyncSession(async_engine) as session:
        config = await get_or_create_config(session)
        assert config.image_preset_id is None


@pytest.mark.asyncio
async def test_rotation_excludes_motd_claimed_devices(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    seed_device: Device,
) -> None:
    """The solo rotation query must skip devices held by a MOTD session."""
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
        device.claimed_by_motd_config_id = uuid4()
        device.scheduled_next_at = utcnow() - timedelta(seconds=10)
        session.add(device)
        await session.commit()

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await _rotate_due_devices(app)
    mock_mqtt.send_command.assert_not_awaited()
