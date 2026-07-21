"""Tests for the rotation cadence feature.

Covers the per-device refresh interval (`next_refresh_at` helper), the
PATCH /api/devices/{id} route, the grid display-schedule update, the
GET /api/schedule/upcoming endpoint, and the UTC serializer that emits
offset-aware ISO strings.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from inky_image_display_api.services.image_service import next_refresh_at
from inky_image_display_shared.models import Device, Grid
from inky_image_display_shared.time import utcnow
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession


class TestNextRefreshAt:
    """The cadence helper should prefer the per-device override."""

    def test_override_wins(self):
        device = Device(
            id=uuid4(),
            device_id="kitchen",
            device_profile_id=uuid4(),
            refresh_interval_seconds=120,
        )
        now = datetime(2026, 5, 17, 12, 0, 0)
        assert next_refresh_at(device, 3600, now) == now + timedelta(seconds=120)

    def test_falls_back_to_default(self):
        device = Device(
            id=uuid4(),
            device_id="kitchen",
            device_profile_id=uuid4(),
            refresh_interval_seconds=None,
        )
        now = datetime(2026, 5, 17, 12, 0, 0)
        assert next_refresh_at(device, 900, now) == now + timedelta(seconds=900)


class TestPatchDevice:
    """PATCH /api/devices/{device_id} controls the cadence override."""

    def test_sets_interval(self, client: TestClient, seed_device: Device):
        resp = client.patch(
            f"/api/devices/{seed_device.device_id}",
            json={"refresh_interval_seconds": 600},
        )
        assert resp.status_code == 200
        assert resp.json()["refresh_interval_seconds"] == 600

    def test_clear_resets_to_default(self, client: TestClient, seed_device: Device):
        client.patch(
            f"/api/devices/{seed_device.device_id}",
            json={"refresh_interval_seconds": 600},
        )
        resp = client.patch(
            f"/api/devices/{seed_device.device_id}",
            json={"clear_refresh_interval": True},
        )
        assert resp.status_code == 200
        assert resp.json()["refresh_interval_seconds"] is None

    def test_rejects_out_of_range(self, client: TestClient, seed_device: Device):
        resp = client.patch(
            f"/api/devices/{seed_device.device_id}",
            json={"refresh_interval_seconds": 0},
        )
        assert resp.status_code == 422

        resp = client.patch(
            f"/api/devices/{seed_device.device_id}",
            json={"refresh_interval_seconds": 7 * 24 * 3600 + 1},
        )
        assert resp.status_code == 422

    def test_404_on_unknown(self, client: TestClient):
        resp = client.patch(
            "/api/devices/nonexistent",
            json={"refresh_interval_seconds": 600},
        )
        assert resp.status_code == 404


class TestGridScheduleUpdate:
    """PUT /api/grids/{grid_id} edits the daily display schedule."""

    @pytest.fixture
    async def seed_grid(self, async_engine: AsyncEngine) -> Grid:
        grid = Grid(name="hallway", width_cm=80.0, height_cm=40.0)
        async with AsyncSession(async_engine) as session:
            session.add(grid)
            await session.commit()
            await session.refresh(grid)
        return grid

    def test_sets_display_schedule(self, client: TestClient, seed_grid: Grid):
        resp = client.put(
            f"/api/grids/{seed_grid.id}",
            json={"display_schedule_enabled": True, "display_time": "07:30", "display_timezone": "Europe/Berlin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_schedule_enabled"] is True
        assert body["display_time"] == "07:30"


@pytest.fixture
async def seed_schedule_entities(
    async_engine: AsyncEngine,
    seed_profile,
) -> tuple[str, str, str]:
    """Seed two solo devices, one scheduled grid, and one grid-claimed device.

    The grid's daily display time is two hours ahead so its computed
    occurrence lands between the two solo devices; the claimed device
    must be excluded from the merged queue.
    """
    now = utcnow()
    grid = Grid(
        id=uuid4(),
        name="hallway",
        width_cm=80.0,
        height_cm=40.0,
        display_schedule_enabled=True,
        # Next occurrence of "now + 2h" wall-clock is always ~2h away,
        # even across midnight, so it sorts between the solo devices.
        display_time=(now + timedelta(hours=2)).strftime("%H:%M"),
        display_weekday_mask=127,
        display_timezone="UTC",
    )
    solo_a = Device(
        id=uuid4(),
        device_id="solo-a",
        device_profile_id=seed_profile.id,
        is_online=True,
        scheduled_next_at=now + timedelta(hours=1),
    )
    solo_b = Device(
        id=uuid4(),
        device_id="solo-b",
        device_profile_id=seed_profile.id,
        is_online=True,
        scheduled_next_at=now + timedelta(hours=3),
    )
    claimed = Device(
        id=uuid4(),
        device_id="claimed",
        device_profile_id=seed_profile.id,
        is_online=True,
        claimed_by_grid_id=grid.id,
        scheduled_next_at=now + timedelta(minutes=90),
    )
    # Capture strings before the session closes — SQLAlchemy expires
    # attributes on commit/close, so reading after the context exits
    # triggers a DetachedInstanceError.
    a_name = solo_a.device_id
    g_name = grid.name
    b_name = solo_b.device_id
    async with AsyncSession(async_engine) as session:
        session.add_all([grid, solo_a, solo_b, claimed])
        await session.commit()
    return a_name, g_name, b_name


class TestScheduleUpcoming:
    """GET /api/schedule/upcoming merges devices + grids chronologically."""

    def test_chronological_merge_and_exclusion(
        self,
        client: TestClient,
        seed_schedule_entities: tuple[str, str, str],
    ):
        a_name, grid_name, b_name = seed_schedule_entities
        resp = client.get("/api/schedule/upcoming", params={"limit": 10})
        assert resp.status_code == 200
        entries = resp.json()
        kinds_and_names = [(e["kind"], e["name"]) for e in entries]
        assert ("device", "claimed") not in kinds_and_names
        assert kinds_and_names[:3] == [
            ("device", a_name),
            ("grid", grid_name),
            ("device", b_name),
        ]

    def test_effective_interval_falls_back_to_default(
        self,
        client: TestClient,
        seed_device: Device,
        mock_settings: MagicMock,
    ):
        resp = client.get("/api/schedule/upcoming")
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["refresh_interval_seconds"] is None
        assert entries[0]["effective_interval_seconds"] == mock_settings.default_display_duration


class TestUtcSerialization:
    """Datetime fields on responses must be offset-aware UTC."""

    def test_device_scheduled_next_at_is_offset_aware(
        self,
        client: TestClient,
        seed_device: Device,
    ):
        resp = client.get(f"/api/devices/{seed_device.device_id}")
        assert resp.status_code == 200
        value = resp.json()["scheduled_next_at"]
        # ISO strings from Pydantic with UTC offset end in "+00:00"
        assert value.endswith("+00:00")
