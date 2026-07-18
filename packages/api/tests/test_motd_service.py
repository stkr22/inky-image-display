"""Tests for MOTD orchestration: generation, sessions, rotation, release."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

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
    DeviceProfile,
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
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what", "why"])
    await _seed_ready_message(async_engine, config, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

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
    mock_s3_service: MagicMock,
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
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)


@pytest.mark.asyncio
async def test_start_session_without_message_raises(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    with pytest.raises(MotdStartError, match="No generated message"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)


async def _seed_extra_device(async_engine: AsyncEngine, profile_id: UUID, device_id: str, orientation: str) -> Device:
    device = Device(
        id=uuid4(),
        device_id=device_id,
        device_profile_id=profile_id,
        display_orientation=orientation,
        is_online=True,
    )
    async with AsyncSession(async_engine) as session:
        session.add(device)
        await session.commit()
        await session.refresh(device)
    return device


async def _add_assignment(async_engine: AsyncEngine, config: MotdConfig, device: Device, parts: list[str]) -> None:
    async with AsyncSession(async_engine) as session:
        session.add(MotdDeviceAssignment(config_id=config.id, device_id=device.id, parts=json.dumps(parts)))
        await session.commit()


@pytest.mark.asyncio
async def test_start_session_renders_missing_screens_on_demand(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """A part assigned after generation is rendered at session start."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["why"])
    # The message was generated while the assignment was still "what".
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

    assert result.displayed == [seed_device.device_id]
    assert result.skipped_no_content == []
    command = mock_mqtt.send_command.await_args.args[1]
    assert command.image_path.endswith("why_1600x1200.jpg")
    mock_s3_service.upload_image.assert_called_once()
    async with AsyncSession(async_engine) as session:
        screens = (await session.exec(select(MotdScreen))).all()
        assert {screen.part for screen in screens} == {"what", "why"}


@pytest.mark.asyncio
async def test_start_session_refits_image_for_new_panel_size(  # noqa: PLR0913 — all six are fixtures
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
    seed_profile: DeviceProfile,
) -> None:
    """A panel size assigned the image part after generation re-fits an existing screen."""
    portrait = await _seed_extra_device(async_engine, seed_profile.id, "test-portrait", "portrait")
    config = await _seed_config_with_assignment(async_engine, seed_device, ["image"])
    await _add_assignment(async_engine, config, portrait, ["image"])
    message = await _seed_ready_message(async_engine, config, ["image"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    mock_s3_service.get_object_bytes = MagicMock(return_value=_tiny_jpeg())

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

    assert set(result.displayed) == {seed_device.device_id, portrait.device_id}
    mock_s3_service.get_object_bytes.assert_called_once_with(f"motd/{message.id}/image_1600x1200.jpg")
    async with AsyncSession(async_engine) as session:
        screens = (await session.exec(select(MotdScreen))).all()
        assert {(screen.part, screen.width, screen.height) for screen in screens} == {
            ("image", 1600, 1200),
            ("image", 1200, 1600),
        }


@pytest.mark.asyncio
async def test_start_session_cannot_conjure_missing_illustration(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Without any rendered image screen the image part stays missing."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["image"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    with pytest.raises(MotdStartError, match="could be claimed"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)
    mock_s3_service.upload_image.assert_not_called()


@pytest.mark.asyncio
async def test_start_session_redisplays_specific_message(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """An explicit message_id displays that message, not the latest, and stamps displayed_at."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    older = await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, message_id=older.id)

    assert result.message_id == older.id
    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        assert db_config.active_message_id == older.id
        message = (await session.exec(select(MotdMessage).where(col(MotdMessage.id) == older.id))).one()
        assert message.displayed_at is not None


@pytest.mark.asyncio
async def test_start_session_rejects_unknown_or_unready_message(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    with pytest.raises(MotdStartError, match="no longer exists"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, message_id=uuid4())

    async with AsyncSession(async_engine) as session:
        failed = MotdMessage(config_id=config.id, status="failed")
        session.add(failed)
        await session.commit()
        await session.refresh(failed)
    with pytest.raises(MotdStartError, match="not ready"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, message_id=failed.id)


@pytest.mark.asyncio
async def test_prune_keeps_recent_active_and_latest_ready(
    async_engine: AsyncEngine,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Retention is time-based, but the active and newest ready messages survive."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    old_plain = await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    old_active = await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    recent = await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    async with AsyncSession(async_engine) as session:
        for message_id, days in ((old_plain.id, 9), (old_active.id, 8), (recent.id, 0)):
            message = (await session.exec(select(MotdMessage).where(col(MotdMessage.id) == message_id))).one()
            message.created_at = utcnow() - timedelta(days=days)
            session.add(message)
        db_config = (await session.exec(select(MotdConfig))).one()
        db_config.active_message_id = old_active.id
        session.add(db_config)
        await session.commit()

    await motd_service._prune_old_messages(async_engine, mock_s3_service, config.id)

    async with AsyncSession(async_engine) as session:
        remaining = {m.id for m in (await session.exec(select(MotdMessage))).all()}
        assert remaining == {old_active.id, recent.id}
        screens = (await session.exec(select(MotdScreen))).all()
        assert {s.message_id for s in screens} == {old_active.id, recent.id}
    mock_s3_service.delete_object.assert_called_once()


@pytest.mark.asyncio
async def test_resync_pushes_changed_assignment(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Editing a claimed device's parts mid-session renders and pushes the new part."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)
    assert mock_mqtt.send_command.await_count == 1

    async with AsyncSession(async_engine) as session:
        assignment = (await session.exec(select(MotdDeviceAssignment))).one()
        assignment.parts = json.dumps(["takeaway"])
        session.add(assignment)
        await session.commit()

    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        await motd_service.resync_active_session(
            session,
            mock_mqtt,
            mock_settings,
            mock_s3_service,
            db_config,
            {seed_device.id: ["what"]},
        )

    assert mock_mqtt.send_command.await_count == 2
    command = mock_mqtt.send_command.await_args.args[1]
    assert command.image_path.endswith("takeaway_1600x1200.jpg")
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_motd_config_id == config.id
        assignment = (await session.exec(select(MotdDeviceAssignment))).one()
        assert assignment.rotation_index == 0


@pytest.mark.asyncio
async def test_resync_releases_removed_device_and_keeps_unchanged(  # noqa: PLR0913 — all six are fixtures
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
    seed_profile: DeviceProfile,
) -> None:
    """Unchanged devices keep their screen; devices dropped from the list are released."""
    second = await _seed_extra_device(async_engine, seed_profile.id, "test-second", "landscape")
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _add_assignment(async_engine, config, second, ["why"])
    await _seed_ready_message(async_engine, config, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)
    assert mock_mqtt.send_command.await_count == 2

    async with AsyncSession(async_engine) as session:
        assignments = (await session.exec(select(MotdDeviceAssignment))).all()
        for assignment in assignments:
            if assignment.device_id == second.id:
                await session.delete(assignment)
        await session.commit()

    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        await motd_service.resync_active_session(
            session,
            mock_mqtt,
            mock_settings,
            mock_s3_service,
            db_config,
            {seed_device.id: ["what"], second.id: ["why"]},
        )

    # No extra e-ink refresh for the unchanged device, no push for the removed one.
    assert mock_mqtt.send_command.await_count == 2
    async with AsyncSession(async_engine) as session:
        kept = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
        released = (await session.exec(select(Device).where(col(Device.id) == second.id))).one()
        assert kept.claimed_by_motd_config_id == config.id
        assert released.claimed_by_motd_config_id is None
        assert released.scheduled_next_at <= utcnow()


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
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """A due, claimed device advances through its parts and wraps around."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what", "why"])
    await _seed_ready_message(async_engine, config, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

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
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Single-part devices are parked, not re-pushed every interval."""
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)
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
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

    before = utcnow()
    async with AsyncSession(async_engine) as session:
        db_config = (await session.exec(select(MotdConfig))).one()
        await release_session(session, db_config, mock_settings)

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_motd_config_id is None
        # Rejoin is jittered within the refresh interval (default 3600s here).
        assert device.scheduled_next_at >= before - timedelta(seconds=1)
        assert device.scheduled_next_at <= before + timedelta(seconds=3601)
        db_config = (await session.exec(select(MotdConfig))).one()
        assert db_config.active_message_id is None
        assignment = (await session.exec(select(MotdDeviceAssignment))).one()
        assert assignment.rotation_index == 0


@pytest.mark.asyncio
async def test_release_staggers_devices_to_avoid_synchronized_refreshes(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """The MOTD pushes all panels at once; release must not rejoin them in
    lockstep or they keep flashing simultaneously every interval after."""
    second = Device(
        id=uuid4(),
        device_id="test-display-2",
        room="Kitchen",
        device_profile_id=seed_device.device_profile_id,
        display_orientation="landscape",
        is_online=True,
        last_seen=datetime.now(),
    )
    async with AsyncSession(async_engine) as session:
        session.add(second)
        await session.commit()
        await session.refresh(second)

    config = await _seed_config_with_assignment(async_engine, seed_device, ["what"])
    async with AsyncSession(async_engine) as session:
        session.add(MotdDeviceAssignment(config_id=config.id, device_id=second.id, parts=json.dumps(["what"])))
        await session.commit()
    await _seed_ready_message(async_engine, config, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

    before = utcnow()
    with patch.object(motd_service.random, "uniform", side_effect=[600.0, 1800.0]) as uniform:
        async with AsyncSession(async_engine) as session:
            db_config = (await session.exec(select(MotdConfig))).one()
            await release_session(session, db_config, mock_settings)
    # Jitter is drawn per device over its full refresh interval.
    assert uniform.call_count == 2
    assert uniform.call_args_list[0].args == (0, 3600)

    async with AsyncSession(async_engine) as session:
        devices = (await session.exec(select(Device))).all()
        offsets = sorted((d.scheduled_next_at - before).total_seconds() for d in devices)
        assert offsets[0] == pytest.approx(600, abs=2)
        assert offsets[1] == pytest.approx(1800, abs=2)


@pytest.mark.asyncio
async def test_expired_session_is_released_by_tick(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
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
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service)

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
