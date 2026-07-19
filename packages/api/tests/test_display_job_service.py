"""Tests for display-job orchestration: generation, sessions, rotation, release."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from inky_image_display_api.services import display_job_service
from inky_image_display_api.services.display_job_service import (
    JobStartError,
    advance_due_slots,
    display_due,
    generate_message,
    generation_due,
    release_session,
    start_session,
)
from inky_image_display_shared.ai import MotdStory
from inky_image_display_shared.models import (
    Device,
    DisplayJob,
    DisplayJobSlot,
    Grid,
    GridDevice,
    MotdMessage,
    MotdScreen,
)
from inky_image_display_shared.models import (
    Image as ImageModel,
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


async def _seed_grid(engine: AsyncEngine, devices: list[Device]) -> Grid:
    """A one-row grid with the given devices side by side (slot cols 0..n)."""
    grid = Grid(name=f"grid-{uuid4()}", width_cm=27.1 * len(devices), height_cm=20.3)
    async with AsyncSession(engine) as session:
        session.add(grid)
        await session.flush()
        for index, device in enumerate(devices):
            session.add(
                GridDevice(
                    grid_id=grid.id,
                    device_id=device.id,
                    row=0,
                    col=index,
                    top_left_x_cm=27.1 * index,
                    top_left_y_cm=0.0,
                    width_cm=27.1,
                    height_cm=20.3,
                )
            )
        await session.commit()
        await session.refresh(grid)
    return grid


async def _seed_job(engine: AsyncEngine, grid: Grid | None, slots: dict[tuple[int, int], list[str]]) -> DisplayJob:
    job = DisplayJob(name=f"job-{uuid4()}", target_grid_id=grid.id if grid else None)
    async with AsyncSession(engine) as session:
        session.add(job)
        await session.flush()
        for (row, column), parts in slots.items():
            session.add(DisplayJobSlot(job_id=job.id, row=row, col=column, parts=json.dumps(parts)))
        await session.commit()
        await session.refresh(job)
    return job


async def _seed_ready_message(
    engine: AsyncEngine, job: DisplayJob, parts: list[str], dims: tuple[int, int]
) -> MotdMessage:
    width, height = dims
    async with AsyncSession(engine) as session:
        message = MotdMessage(
            job_id=job.id,
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


@pytest.mark.asyncio
async def test_generate_message_renders_screens_per_slot(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Full generation path: story + screens for the mapped parts/dims."""
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what", "why+takeaway", "qr"]})

    with patch(
        "inky_image_display_api.services.display_job_service.generate_motd_story",
        new=AsyncMock(return_value=(STORY, "https://news.example/bridge")),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, job_id=job.id, task_id=uuid4())

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
        db_job = (await session.exec(select(DisplayJob))).one()
        assert db_job.last_run_at is not None
    assert mock_s3_service.upload_image.call_count == 3


@pytest.mark.asyncio
async def test_generate_message_without_source_url_skips_qr(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    mock_settings.gemini_api_key = MagicMock(get_secret_value=MagicMock(return_value="dummy"))
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what", "qr"]})

    with patch(
        "inky_image_display_api.services.display_job_service.generate_motd_story",
        new=AsyncMock(return_value=(STORY, None)),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, job_id=job.id, task_id=uuid4())

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
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["image"]})

    fake_image = AsyncMock(return_value=_tiny_jpeg())
    fake_preset = MagicMock(model_name="gemini-image")
    with (
        patch(
            "inky_image_display_api.services.display_job_service.generate_motd_story",
            new=AsyncMock(return_value=(STORY, None)),
        ),
        patch(
            "inky_image_display_api.services.display_job_service.resolve_preset",
            new=AsyncMock(return_value=(fake_preset, {})),
        ),
        patch(
            "inky_image_display_api.services.display_job_service.build_rendered_prompt",
            return_value=MagicMock(),
        ),
        patch("inky_image_display_api.services.display_job_service.generate_image_bytes", new=fake_image),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, job_id=job.id, task_id=uuid4())

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
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})

    with patch(
        "inky_image_display_api.services.display_job_service.generate_motd_story",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await generate_message(async_engine, mock_settings, mock_s3_service, job_id=job.id, task_id=uuid4())

    async with AsyncSession(async_engine) as session:
        message = (await session.exec(select(MotdMessage))).one()
        assert message.status == "failed"
        assert message.error == "boom"


@pytest.mark.asyncio
async def test_start_session_claims_grid_and_pushes(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what", "why"]})
    await _seed_ready_message(async_engine, job, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

    assert result.displayed == [seed_device.device_id]
    command = mock_mqtt.send_command.await_args.args[1]
    assert command.image_path.endswith("what_1600x1200.jpg")
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_grid_id == grid.id
        db_grid = (await session.exec(select(Grid))).one()
        assert db_grid.active_message_id is not None
        assert db_grid.active_expires_at is None  # default duration = indefinite


@pytest.mark.asyncio
async def test_start_session_on_unknown_grid_raises(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
) -> None:
    with pytest.raises(JobStartError, match="grid no longer exists"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, uuid4())


@pytest.mark.asyncio
async def test_start_session_without_message_raises(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    grid = await _seed_grid(async_engine, [seed_device])
    await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    with pytest.raises(JobStartError, match="No generated message"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)


@pytest.mark.asyncio
async def test_start_session_renders_missing_screens_on_demand(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """A part mapped after generation is rendered at session start."""
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["why"]})
    # The message was generated while the slot mapping was still "what".
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

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
    seed_profile,
) -> None:
    """A panel size mapped the image part after generation re-fits an existing screen."""
    portrait = await _seed_extra_device(async_engine, seed_profile.id, "test-portrait", "portrait")
    grid = await _seed_grid(async_engine, [seed_device, portrait])
    job = await _seed_job(async_engine, grid, {(0, 0): ["image"], (0, 1): ["image"]})
    message = await _seed_ready_message(async_engine, job, ["image"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    mock_s3_service.get_object_bytes = MagicMock(return_value=_tiny_jpeg())

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

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
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["image"]})
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    with pytest.raises(JobStartError, match="No grid slot has content"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)
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
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    older = await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)

    result = await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id, message_id=older.id)

    assert result.message_id == older.id
    async with AsyncSession(async_engine) as session:
        db_grid = (await session.exec(select(Grid))).one()
        assert db_grid.active_message_id == older.id
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
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    with pytest.raises(JobStartError, match="no longer exists"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id, message_id=uuid4())

    async with AsyncSession(async_engine) as session:
        failed = MotdMessage(job_id=job.id, status="failed")
        session.add(failed)
        await session.commit()
        await session.refresh(failed)
    with pytest.raises(JobStartError, match="not ready"):
        await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id, message_id=failed.id)


@pytest.mark.asyncio
async def test_prune_keeps_recent_active_and_latest_ready(
    async_engine: AsyncEngine,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Retention is time-based, but the active and newest ready messages survive."""
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    old_plain = await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    old_active = await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    recent = await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    async with AsyncSession(async_engine) as session:
        for message_id, days in ((old_plain.id, 9), (old_active.id, 8), (recent.id, 0)):
            message = (await session.exec(select(MotdMessage).where(col(MotdMessage.id) == message_id))).one()
            message.created_at = utcnow() - timedelta(days=days)
            session.add(message)
        db_grid = (await session.exec(select(Grid))).one()
        db_grid.active_message_id = old_active.id
        session.add(db_grid)
        await session.commit()

    await display_job_service._prune_old_messages(async_engine, mock_s3_service, job.id)

    async with AsyncSession(async_engine) as session:
        remaining = {m.id for m in (await session.exec(select(MotdMessage))).all()}
        assert remaining == {old_active.id, recent.id}
        screens = (await session.exec(select(MotdScreen))).all()
        assert {s.message_id for s in screens} == {old_active.id, recent.id}
    mock_s3_service.delete_object.assert_called_once()


@pytest.mark.asyncio
async def test_resync_pushes_changed_slot(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Editing a slot's parts mid-session renders and pushes the new part."""
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)
    assert mock_mqtt.send_command.await_count == 1

    async with AsyncSession(async_engine) as session:
        slot = (await session.exec(select(DisplayJobSlot))).one()
        slot.parts = json.dumps(["takeaway"])
        session.add(slot)
        await session.commit()

    async with AsyncSession(async_engine) as session:
        db_job = (await session.exec(select(DisplayJob))).one()
        await display_job_service.resync_active_session(
            session,
            mock_mqtt,
            mock_settings,
            mock_s3_service,
            db_job,
            {(0, 0): ["what"]},
        )

    assert mock_mqtt.send_command.await_count == 2
    command = mock_mqtt.send_command.await_args.args[1]
    assert command.image_path.endswith("takeaway_1600x1200.jpg")
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_grid_id == grid.id
        slot = (await session.exec(select(DisplayJobSlot))).one()
        assert slot.rotation_index == 0


@pytest.mark.asyncio
async def test_resync_releases_removed_slot_and_keeps_unchanged(  # noqa: PLR0913 — all six are fixtures
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
    seed_profile,
) -> None:
    """Unchanged slots keep their screen; slots dropped from the mapping release their panel."""
    second = await _seed_extra_device(async_engine, seed_profile.id, "test-second", "landscape")
    grid = await _seed_grid(async_engine, [seed_device, second])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"], (0, 1): ["why"]})
    await _seed_ready_message(async_engine, job, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)
    assert mock_mqtt.send_command.await_count == 2

    async with AsyncSession(async_engine) as session:
        slots = (await session.exec(select(DisplayJobSlot))).all()
        for slot in slots:
            if slot.col == 1:
                await session.delete(slot)
        await session.commit()

    async with AsyncSession(async_engine) as session:
        db_job = (await session.exec(select(DisplayJob))).one()
        await display_job_service.resync_active_session(
            session,
            mock_mqtt,
            mock_settings,
            mock_s3_service,
            db_job,
            {(0, 0): ["what"], (0, 1): ["why"]},
        )

    # No extra e-ink refresh for the unchanged slot, no push for the removed one.
    assert mock_mqtt.send_command.await_count == 2
    async with AsyncSession(async_engine) as session:
        kept = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
        released = (await session.exec(select(Device).where(col(Device.id) == second.id))).one()
        assert kept.claimed_by_grid_id == grid.id
        assert released.claimed_by_grid_id is None


def _make_app(engine: AsyncEngine, settings: MagicMock, mqtt: MagicMock) -> MagicMock:
    app = MagicMock()
    app.state.engine = engine
    app.state.settings = settings
    app.state.mqtt = mqtt
    app.state.display_job_generation_inflight = set()
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
    """A due, claimed panel advances through its slot's parts and wraps around."""
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what", "why"]})
    await _seed_ready_message(async_engine, job, ["what", "why"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    for expected_part in ("why", "what"):
        async with AsyncSession(async_engine) as session:
            device = (await session.exec(select(Device))).one()
            device.scheduled_next_at = utcnow() - timedelta(seconds=1)
            session.add(device)
            await session.commit()
        await advance_due_slots(app)
        command = mock_mqtt.send_command.await_args.args[1]
        assert f"{expected_part}_1600x1200" in command.image_path

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.scheduled_next_at > utcnow()


@pytest.mark.asyncio
async def test_advance_parks_single_part_slot(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """Single-part slots are parked, not re-pushed every interval."""
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)
    assert mock_mqtt.send_command.await_count == 1

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        device.scheduled_next_at = utcnow() - timedelta(seconds=1)
        session.add(device)
        await session.commit()
    await advance_due_slots(app)
    assert mock_mqtt.send_command.await_count == 1  # no extra e-ink refresh


@pytest.mark.asyncio
async def test_release_without_pool_returns_devices_to_solo_rotation(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

    before = utcnow()
    async with AsyncSession(async_engine) as session:
        db_grid = (await session.exec(select(Grid))).one()
        await release_session(session, db_grid, mock_settings)

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_grid_id is None
        # Rejoin is jittered within the refresh interval (default 3600s here).
        assert device.scheduled_next_at >= before - timedelta(seconds=1)
        assert device.scheduled_next_at <= before + timedelta(seconds=3601)
        db_grid = (await session.exec(select(Grid))).one()
        assert db_grid.active_message_id is None
        slot = (await session.exec(select(DisplayJobSlot))).one()
        assert slot.rotation_index == 0


@pytest.mark.asyncio
async def test_release_staggers_devices_to_avoid_synchronized_refreshes(  # noqa: PLR0913 — all six are fixtures
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
    seed_profile,
) -> None:
    """A session pushes all panels at once; release must not rejoin them in
    lockstep or they keep flashing simultaneously every interval after."""
    second = await _seed_extra_device(async_engine, seed_profile.id, "test-display-2", "landscape")
    grid = await _seed_grid(async_engine, [seed_device, second])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"], (0, 1): ["what"]})
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

    before = utcnow()
    with patch.object(display_job_service.random, "uniform", side_effect=[600.0, 1800.0]) as uniform:
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid))).one()
            await release_session(session, db_grid, mock_settings)
    # Jitter is drawn per device over its full refresh interval.
    assert uniform.call_count == 2
    assert uniform.call_args_list[0].args == (0, 3600)

    async with AsyncSession(async_engine) as session:
        devices = (await session.exec(select(Device))).all()
        offsets = sorted((d.scheduled_next_at - before).total_seconds() for d in devices)
        assert offsets[0] == pytest.approx(600, abs=2)
        assert offsets[1] == pytest.approx(1800, abs=2)


@pytest.mark.asyncio
async def test_release_with_pool_resumes_grid_rotation_with_jitter(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    """A grid with pool images keeps its claims; only its next tick is jittered."""
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    async with AsyncSession(async_engine) as session:
        session.add(
            ImageModel(
                source_name="manual",
                storage_path="manual/pool.jpg",
                is_portrait=False,
                target_grid_id=grid.id,
            )
        )
        await session.commit()
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

    before = utcnow()
    with patch.object(display_job_service.random, "uniform", return_value=900.0) as uniform:
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid))).one()
            await release_session(session, db_grid, mock_settings)
    uniform.assert_called_once()

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_grid_id == grid.id  # grid resumes pool rotation
        db_grid = (await session.exec(select(Grid))).one()
        assert (db_grid.scheduled_next_at - before).total_seconds() == pytest.approx(900, abs=2)


@pytest.mark.asyncio
async def test_expired_session_is_released_by_tick(
    async_engine: AsyncEngine,
    mock_settings: MagicMock,
    mock_mqtt: MagicMock,
    mock_s3_service: MagicMock,
    seed_device: Device,
) -> None:
    grid = await _seed_grid(async_engine, [seed_device])
    job = await _seed_job(async_engine, grid, {(0, 0): ["what"]})
    async with AsyncSession(async_engine) as session:
        db_grid = (await session.exec(select(Grid))).one()
        db_grid.display_duration_seconds = 60
        session.add(db_grid)
        await session.commit()
    await _seed_ready_message(async_engine, job, ["what"], (1600, 1200))
    mock_mqtt.is_connected = MagicMock(return_value=True)
    await start_session(async_engine, mock_mqtt, mock_settings, mock_s3_service, grid.id)

    async with AsyncSession(async_engine) as session:
        db_grid = (await session.exec(select(Grid))).one()
        assert db_grid.active_expires_at is not None
        db_grid.active_expires_at = utcnow() - timedelta(seconds=1)
        session.add(db_grid)
        await session.commit()

    app = _make_app(async_engine, mock_settings, mock_mqtt)
    await display_job_service.tick(app)

    async with AsyncSession(async_engine) as session:
        device = (await session.exec(select(Device))).one()
        assert device.claimed_by_grid_id is None
        db_grid = (await session.exec(select(Grid))).one()
        assert db_grid.active_message_id is None


def test_generation_due_follows_interval() -> None:
    """Generation runs on the job's own interval lease, like the sync jobs."""
    now = datetime(2026, 7, 1, 7, 30)
    job = DisplayJob(name="test", target_grid_id=uuid4())

    assert not generation_due(job, now)  # no interval → manual only

    job.interval_minutes = 1440
    job.next_run_at = now - timedelta(minutes=1)
    assert generation_due(job, now)
    job.next_run_at = now + timedelta(minutes=1)
    assert not generation_due(job, now)

    # A job without a target grid has nothing to render for.
    job.next_run_at = now - timedelta(minutes=1)
    job.target_grid_id = None
    assert not generation_due(job, now)


def test_display_due_follows_grid_schedule() -> None:
    """Weekday mask, display time and once-per-day guard drive the grid tick."""
    grid = Grid(
        name="test",
        width_cm=27.1,
        height_cm=20.3,
        display_schedule_enabled=True,
        display_time="08:00",
        display_weekday_mask=127,
        display_timezone="UTC",
    )
    before_display = datetime(2026, 7, 1, 7, 30)
    after_display = datetime(2026, 7, 1, 8, 5)

    assert not display_due(grid, before_display)
    assert display_due(grid, after_display)

    grid.last_displayed_on = after_display.date()
    assert not display_due(grid, after_display)
    grid.last_displayed_on = None

    # An active session blocks a re-start.
    grid.active_message_id = uuid4()
    assert not display_due(grid, after_display)
    grid.active_message_id = None

    # Wednesday 2026-07-01; mask without Wednesday (bit 2) → nothing fires.
    grid.display_weekday_mask = 127 & ~(1 << 2)
    assert not display_due(grid, after_display)

    grid.display_weekday_mask = 127
    grid.display_schedule_enabled = False
    assert not display_due(grid, after_display)


def test_display_schedule_respects_timezone() -> None:
    """08:00 in Berlin (UTC+2 in July) is 06:00 UTC."""
    grid = Grid(
        name="tz-test",
        width_cm=27.1,
        height_cm=20.3,
        display_schedule_enabled=True,
        display_time="08:00",
        display_weekday_mask=127,
        display_timezone="Europe/Berlin",
    )
    assert not display_due(grid, datetime(2026, 7, 1, 5, 55))
    assert display_due(grid, datetime(2026, 7, 1, 6, 5))


def _tiny_jpeg() -> bytes:
    out = BytesIO()
    Image.new("RGB", (64, 48), "#446688").save(out, format="JPEG")
    return out.getvalue()
