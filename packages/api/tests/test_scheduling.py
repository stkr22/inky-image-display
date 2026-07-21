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
from inky_image_display_api.services.sync_job_scheduling import next_cron_run, validate_cron
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
            json={"display_schedule_enabled": True, "display_cron": "30 7 * * *", "display_timezone": "Europe/Berlin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_schedule_enabled"] is True
        assert body["display_cron"] == "30 7 * * *"


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
        # The upcoming endpoint reads the lease directly; +2h sorts the
        # grid between the two solo devices.
        display_next_at=now + timedelta(hours=2),
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


class TestCronScheduling:
    """The cron helpers behind job schedules and the preview endpoint."""

    def test_next_cron_run_is_strictly_future_naive_utc(self):
        now = datetime(2026, 7, 1, 12, 0, 0)
        result = next_cron_run("0 12 * * *", "UTC", now)
        assert result == datetime(2026, 7, 2, 12, 0, 0)
        assert result.tzinfo is None

    def test_next_cron_run_evaluates_in_timezone(self):
        # Berlin is UTC+2 in July: daily 06:00 local = 04:00 UTC.
        result = next_cron_run("0 6 * * *", "Europe/Berlin", datetime(2026, 7, 1, 0, 0, 0))
        assert result == datetime(2026, 7, 1, 4, 0, 0)

    def test_validate_cron_rejects_garbage(self):
        with pytest.raises(ValueError, match="Invalid cron"):
            validate_cron("not a cron")
        assert validate_cron("*/15 * * * *") == "*/15 * * * *"

    def test_cron_preview_endpoint(self, client: TestClient):
        resp = client.post("/api/schedule/cron-preview", json={"cron": "0 6 * * *", "timezone": "Europe/Berlin"})
        assert resp.status_code == 200
        runs = resp.json()["next_runs"]
        assert len(runs) == 3
        assert all(value.endswith("+00:00") for value in runs)

    def test_cron_preview_rejects_bad_input(self, client: TestClient):
        assert client.post("/api/schedule/cron-preview", json={"cron": "banana"}).status_code == 422
        bad_tz = {"cron": "0 6 * * *", "timezone": "Mars/Olympus"}
        assert client.post("/api/schedule/cron-preview", json=bad_tz).status_code == 422

    def test_worker_status_endpoint(self, client: TestClient):
        resp = client.get("/api/schedule/worker-status")
        assert resp.status_code == 200
        assert resp.json() == {"online": False}


def _load_migration(filename: str):
    """Load a migration module by file — digit-prefixed names aren't importable."""
    import importlib.util  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    path = Path(__file__).resolve().parents[1] / "src/inky_image_display_api/_migrations/versions" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestIntervalToCronMigration:
    """The 0026 backfill maps minute intervals to the nearest cron shape."""

    def test_mappings_keep_the_anchor_wall_clock(self):
        interval_to_cron = _load_migration("0026_job_schedules_to_cron.py").interval_to_cron
        anchor = datetime(2026, 7, 21, 6, 25)  # a Tuesday
        assert interval_to_cron(30, anchor) == "*/30 * * * *"
        assert interval_to_cron(45, None) == "*/30 * * * *"  # rounded to a divisor of 60
        assert interval_to_cron(60, anchor) == "25 * * * *"
        assert interval_to_cron(360, anchor) == "25 */6 * * *"
        assert interval_to_cron(1440, anchor) == "25 6 * * *"
        assert interval_to_cron(7 * 1440, anchor) == "25 6 * * 2"


class TestGridScheduleMigration:
    """The 0027 conversion of grid time+weekday-mask schedules to cron."""

    def test_mask_to_cron(self):
        mask_to_cron = _load_migration("0027_grid_schedule_to_cron.py").mask_to_cron
        assert mask_to_cron("08:00", 127) == "0 8 * * *"
        # Mask bit 0 = Monday → cron 1; bit 6 = Sunday → cron 0.
        assert mask_to_cron("07:30", 0b0000011) == "30 7 * * 1,2"
        assert mask_to_cron("18:05", 0b1000000) == "5 18 * * 0"
        assert mask_to_cron("06:00", 0b0011111) == "0 6 * * 1,2,3,4,5"

    def test_backfill_lease_fires_missed_slot_today(self):
        backfill_lease = _load_migration("0027_grid_schedule_to_cron.py").backfill_lease
        now = datetime(2026, 7, 21, 10, 0)  # 08:00 UTC slot already passed
        # Not shown today → due immediately, like the old date-guard.
        assert backfill_lease("0 8 * * *", "UTC", None, now) == now
        # Already shown today → next occurrence (tomorrow 08:00).
        assert backfill_lease("0 8 * * *", "UTC", "2026-07-21", now) == datetime(2026, 7, 22, 8, 0)
        # Slot still ahead today → today's occurrence.
        assert backfill_lease("0 18 * * *", "UTC", None, now) == datetime(2026, 7, 21, 18, 0)


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
