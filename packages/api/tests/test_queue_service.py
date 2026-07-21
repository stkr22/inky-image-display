"""Queue playback tests: ordering, spreads, holds, release semantics."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from inky_image_display_api.services import queue_service
from inky_image_display_shared.models import Device, Grid, GridDevice, Image, ImageGroup
from inky_image_display_shared.time import utcnow
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from inky_image_display_shared.models import DeviceProfile
    from sqlalchemy.ext.asyncio import AsyncEngine

NOW = utcnow()


def _image(grid_id=None, *, group_id=None, position=0, shown=None, slot=None) -> Image:
    return Image(
        source_name="manual",
        storage_path=f"manual/{uuid4()}.jpg",
        target_grid_id=grid_id,
        group_id=group_id,
        queue_position=position,
        last_displayed_at=shown,
        group_slot_row=slot[0] if slot else None,
        group_slot_col=slot[1] if slot else None,
        original_width=1600,
        original_height=1200,
    )


def _app(engine, settings, s3, mqtt):
    state = SimpleNamespace(engine=engine, settings=settings, s3_service=s3, mqtt=mqtt)
    return SimpleNamespace(state=state)


async def _add(engine, *rows) -> None:
    async with AsyncSession(engine) as session:
        for row in rows:
            session.add(row)
        await session.commit()
        for row in rows:
            # Reload so attribute access after the session closes works.
            await session.refresh(row)


async def _grid_with_device(engine, seed_profile: DeviceProfile, **grid_kwargs) -> tuple[Grid, Device]:
    grid = Grid(id=uuid4(), name="wall", width_cm=27.1, height_cm=20.3, **grid_kwargs)
    device = Device(
        id=uuid4(),
        device_id="panel-1",
        device_profile_id=seed_profile.id,
        display_orientation="landscape",
        is_online=True,
        last_seen=NOW,
    )
    placement = GridDevice(
        grid_id=grid.id,
        device_id=device.id,
        row=0,
        col=0,
        top_left_x_cm=0.0,
        top_left_y_cm=0.0,
        width_cm=27.1,
        height_cm=20.3,
    )
    await _add(engine, grid, device, placement)
    return grid, device


class TestQueueOrdering:
    @pytest.mark.asyncio
    async def test_fresh_entries_first_in_operator_order_then_lru(self, async_engine: AsyncEngine) -> None:
        grid = Grid(id=uuid4(), name="wall", width_cm=80.0, height_cm=40.0)
        fresh_b = _image(grid.id, position=2)
        fresh_a = _image(grid.id, position=1)
        shown_old = _image(grid.id, position=0, shown=NOW - timedelta(hours=3))
        shown_recent = _image(grid.id, position=0, shown=NOW - timedelta(hours=1))
        group_fresh = ImageGroup(name="g", target_grid_id=grid.id, queue_position=0)
        await _add(async_engine, grid, fresh_a, fresh_b, shown_old, shown_recent, group_fresh)

        async with AsyncSession(async_engine) as session:
            entries = await queue_service.queue_entries(session, grid.id)
        ids = [obj.id for _, obj in entries]
        assert ids == [group_fresh.id, fresh_a.id, fresh_b.id, shown_old.id, shown_recent.id]

    @pytest.mark.asyncio
    async def test_grouped_and_excluded_images_stay_out_of_the_queue(self, async_engine: AsyncEngine) -> None:
        grid = Grid(id=uuid4(), name="wall", width_cm=80.0, height_cm=40.0)
        group = ImageGroup(name="g", target_grid_id=grid.id)
        member = _image(grid.id, group_id=group.id)
        excluded = _image(grid.id)
        excluded.excluded_from_rotation = True
        loose = _image(grid.id)
        await _add(async_engine, grid, group, member, excluded, loose)

        async with AsyncSession(async_engine) as session:
            entries = await queue_service.queue_entries(session, grid.id)
        assert [(kind, obj.id) for kind, obj in entries] == [("group", group.id), ("image", loose.id)]


class TestSlotImages:
    def test_one_image_per_slot_first_wins(self) -> None:
        first = _image(group_id=uuid4(), slot=(0, 1))
        duplicate = _image(group_id=uuid4(), slot=(0, 1))
        other = _image(group_id=uuid4(), slot=(0, 0))
        slotted = queue_service.slot_images([first, duplicate, other])
        assert slotted == {(0, 1): first, (0, 0): other}

    def test_unassigned_images_are_not_shown(self) -> None:
        images = [_image(group_id=uuid4()), _image(group_id=uuid4())]
        assert queue_service.slot_images(images) == {}


class TestShowHoldRelease:
    @pytest.fixture
    def mqtt(self) -> MagicMock:
        mqtt = MagicMock()
        mqtt.is_connected = MagicMock(return_value=True)
        mqtt.send_command = AsyncMock()
        return mqtt

    @pytest.mark.asyncio
    async def test_start_group_pushes_claims_and_holds(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid, device = await _grid_with_device(async_engine, seed_profile)
        group = ImageGroup(name="story", target_grid_id=grid.id)
        screen = _image(group_id=group.id, slot=(0, 0))
        await _add(async_engine, group, screen)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            db_group = (await session.exec(select(ImageGroup).where(ImageGroup.id == group.id))).one()
            result = await queue_service.start_group(app, session, db_grid, db_group)

        assert result.displayed == ["panel-1"]
        mqtt.send_command.assert_awaited_once()
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            db_device = (await session.exec(select(Device).where(Device.id == device.id))).one()
            db_group = (await session.exec(select(ImageGroup).where(ImageGroup.id == group.id))).one()
            assert db_grid.current_group_id == group.id
            # No duration configured — held until an explicit release.
            assert db_grid.hold_until is not None
            assert db_device.claimed_by_grid_id == grid.id
            assert db_group.last_displayed_at is not None

    @pytest.mark.asyncio
    async def test_show_next_steps_through_the_queue(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid, device = await _grid_with_device(async_engine, seed_profile)
        group = ImageGroup(name="story", target_grid_id=grid.id, queue_position=0)
        screen = _image(group_id=group.id, slot=(0, 0))
        pool_image = _image(grid.id, position=1)
        await _add(async_engine, group, screen, pool_image)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        # Step 1: the fresh group front-runs the queue.
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            assert await queue_service.show_next(app, session, db_grid) is True
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            db_device = (await session.exec(select(Device).where(Device.id == device.id))).one()
            assert db_grid.current_group_id == group.id
            assert db_grid.hold_until is not None
            assert db_device.current_image_id == screen.id

        # Step 2: the group has been shown, so the fresh pool image is next.
        with patch.object(queue_service.grid_service, "render_and_upload", new=AsyncMock(return_value={})):
            async with AsyncSession(async_engine) as session:
                db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
                assert await queue_service.show_next(app, session, db_grid) is True
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            assert db_grid.current_group_id is None
            assert db_grid.current_image_id == pool_image.id

    @pytest.mark.asyncio
    async def test_show_next_skips_group_without_panel_assignments(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid, _device = await _grid_with_device(async_engine, seed_profile)
        group = ImageGroup(name="unassigned", target_grid_id=grid.id, queue_position=0)
        member = _image(group_id=group.id)
        pool_image = _image(grid.id, position=1)
        await _add(async_engine, group, member, pool_image)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        with patch.object(queue_service.grid_service, "render_and_upload", new=AsyncMock(return_value={})):
            async with AsyncSession(async_engine) as session:
                db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
                assert await queue_service.show_next(app, session, db_grid) is True
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            assert db_grid.current_group_id is None
            assert db_grid.current_image_id == pool_image.id

    @pytest.mark.asyncio
    async def test_show_next_with_empty_queue_touches_nothing(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid, _device = await _grid_with_device(async_engine, seed_profile)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            assert await queue_service.show_next(app, session, db_grid) is False
        mqtt.send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_release_returns_devices_to_jittered_solo_rotation(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid, device = await _grid_with_device(async_engine, seed_profile)
        group = ImageGroup(name="story", target_grid_id=grid.id)
        screen = _image(group_id=group.id, slot=(0, 0))
        await _add(async_engine, group, screen)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            db_group = (await session.exec(select(ImageGroup).where(ImageGroup.id == group.id))).one()
            await queue_service.start_group(app, session, db_grid, db_group)

        release_time = utcnow()
        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            await queue_service.release_queue(app, session, db_grid)

        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            db_device = (await session.exec(select(Device).where(Device.id == device.id))).one()
        assert db_grid.hold_until is None
        assert db_grid.current_group_id is None
        assert db_device.claimed_by_grid_id is None
        # Rejoin is jittered within the default interval, not immediate lockstep.
        interval = mock_settings.default_display_duration
        assert db_device.scheduled_next_at <= release_time + timedelta(seconds=interval)


class TestQueueTick:
    @pytest.fixture
    def mqtt(self) -> MagicMock:
        mqtt = MagicMock()
        mqtt.is_connected = MagicMock(return_value=True)
        mqtt.send_command = AsyncMock()
        return mqtt

    @pytest.mark.asyncio
    async def test_expired_hold_releases_the_panels(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid = Grid(id=uuid4(), name="wall", width_cm=27.1, height_cm=20.3, hold_until=NOW - timedelta(minutes=1))
        device = Device(
            id=uuid4(),
            device_id="panel-1",
            device_profile_id=seed_profile.id,
            is_online=True,
            claimed_by_grid_id=grid.id,
        )
        await _add(async_engine, grid, device)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        await queue_service.queue_tick(app)

        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
            db_device = (await session.exec(select(Device).where(Device.id == device.id))).one()
        assert db_grid.hold_until is None
        assert db_device.claimed_by_grid_id is None

    @pytest.mark.asyncio
    async def test_due_schedule_shows_next_entry_and_advances_lease(
        self, async_engine, mock_settings, mock_s3_service, seed_profile, mqtt
    ) -> None:
        grid, _device = await _grid_with_device(
            async_engine,
            seed_profile,
            display_schedule_enabled=True,
            display_cron="0 0 * * *",
            display_next_at=NOW - timedelta(minutes=1),
        )
        group = ImageGroup(name="story", target_grid_id=grid.id)
        screen = _image(group_id=group.id, slot=(0, 0))
        await _add(async_engine, group, screen)
        app = _app(async_engine, mock_settings, mock_s3_service, mqtt)

        await queue_service.queue_tick(app)

        async with AsyncSession(async_engine) as session:
            db_grid = (await session.exec(select(Grid).where(Grid.id == grid.id))).one()
        assert db_grid.current_group_id == group.id
        # The lease advanced to the next cron occurrence, strictly future.
        assert db_grid.display_next_at is not None
        assert db_grid.display_next_at > utcnow()
        mqtt.send_command.assert_awaited_once()

        # A second tick before the next occurrence is a no-op.
        await queue_service.queue_tick(app)
        mqtt.send_command.assert_awaited_once()


class TestDisplayDue:
    def test_due_when_lease_elapsed(self) -> None:
        grid = Grid(
            name="wall",
            width_cm=10,
            height_cm=10,
            display_schedule_enabled=True,
            display_next_at=NOW - timedelta(minutes=1),
        )
        assert queue_service.display_due(grid, NOW) is True
        grid.display_next_at = NOW + timedelta(hours=1)
        assert queue_service.display_due(grid, NOW) is False

    def test_not_due_while_hold_active_disabled_or_unstamped(self) -> None:
        grid = Grid(
            name="wall",
            width_cm=10,
            height_cm=10,
            display_schedule_enabled=True,
            display_next_at=NOW - timedelta(minutes=1),
        )
        grid.hold_until = NOW + timedelta(hours=1)
        assert queue_service.display_due(grid, NOW) is False
        grid.hold_until = None
        grid.display_schedule_enabled = False
        assert queue_service.display_due(grid, NOW) is False
        grid.display_schedule_enabled = True
        grid.display_next_at = None
        assert queue_service.display_due(grid, NOW) is False
