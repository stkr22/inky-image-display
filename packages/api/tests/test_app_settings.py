"""Tests for the operator-tunable app settings (key/value table + routes).

Covers the fallback to env-loaded ``Settings.default_display_duration``
when the row is absent, round-trip persistence via the service helpers,
and the public ``GET``/``PUT /api/app-settings`` endpoints used by the UI,
plus the quiet-hours window evaluation those settings feed.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from inky_image_display_api.services.app_settings_service import (
    DEFAULT_REFRESH_SECONDS_KEY,
    get_default_refresh_seconds,
    is_quiet_now,
    set_default_refresh_seconds,
)
from inky_image_display_shared.models import AppSetting
from inky_image_display_shared.schemas.responses import QuietHoursSettings
from inky_image_display_shared.time import utcnow
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .conftest import make_settings

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from inky_image_display_api.config import Settings
    from sqlalchemy.ext.asyncio import AsyncEngine


class TestGetDefaultRefreshSeconds:
    """Branches not reachable through the routes: corrupted rows."""

    async def test_corrupted_value_falls_back(self, async_engine: AsyncEngine):
        # A garbled row should not take down the rotation loop — we treat
        # it as "no override" rather than raising.
        settings = make_settings(default_display_duration=1234)
        async with AsyncSession(async_engine) as session:
            session.add(AppSetting(key=DEFAULT_REFRESH_SECONDS_KEY, value="not-json"))
            await session.commit()
        async with AsyncSession(async_engine) as session:
            value = await get_default_refresh_seconds(session, settings)
        assert value == 1234


class TestSetDefaultRefreshSeconds:
    """Service-level writes upsert and enforce the same bounds as the route."""

    async def test_rejects_out_of_range(self, async_engine: AsyncEngine):
        async with AsyncSession(async_engine) as session:
            with pytest.raises(ValueError):
                await set_default_refresh_seconds(session, 0)
            with pytest.raises(ValueError):
                await set_default_refresh_seconds(session, 7 * 24 * 3600 + 1)

    async def test_upserts_existing_row(self, async_engine: AsyncEngine):
        async with AsyncSession(async_engine) as session:
            await set_default_refresh_seconds(session, 600)
        async with AsyncSession(async_engine) as session:
            await set_default_refresh_seconds(session, 900)
        async with AsyncSession(async_engine) as session:
            rows = (await session.exec(select(AppSetting))).all()
        assert len(rows) == 1
        assert json.loads(rows[0].value) == 900


class TestAppSettingsRoutes:
    """The public ``/api/app-settings`` endpoint backs the Settings page."""

    def test_get_returns_settings_fallback_when_empty(
        self,
        client: TestClient,
        settings: Settings,
    ):
        resp = client.get("/api/app-settings")
        assert resp.status_code == 200
        assert resp.json()["default_refresh_seconds"] == settings.default_display_duration

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("default_refresh_seconds", 1800),
            ("stagger_rotation", False),
            ("quiet_hours", {"enabled": True, "start": "21:30", "end": "06:45", "timezone": "Europe/Berlin"}),
        ],
    )
    def test_put_persists_and_leaves_other_sections(self, client: TestClient, field: str, value: object):
        before = client.get("/api/app-settings").json()
        resp = client.put("/api/app-settings", json={field: value})
        assert resp.status_code == 200

        after = client.get("/api/app-settings").json()
        assert after[field] == value
        # A partial PUT only touches the section it names.
        assert {k: v for k, v in after.items() if k != field} == {k: v for k, v in before.items() if k != field}

    def test_stagger_rotation_defaults_on(self, client: TestClient):
        assert client.get("/api/app-settings").json()["stagger_rotation"] is True

    def test_invalid_quiet_hours_timezone_is_rejected(self, client: TestClient) -> None:
        payload = {"quiet_hours": {"enabled": True, "start": "21:30", "end": "06:45", "timezone": "Mars/Olympus"}}
        assert client.put("/api/app-settings", json=payload).status_code == 422


class TestQuietHours:
    """``is_quiet_now`` decides whether rotation holds; windows may wrap midnight."""

    def test_disabled_is_never_quiet(self) -> None:
        qh = QuietHoursSettings(enabled=False, start="00:00", end="23:59")
        assert is_quiet_now(qh, utcnow()) is False

    def test_window_within_one_day(self) -> None:
        qh = QuietHoursSettings(enabled=True, start="08:00", end="17:00", timezone="UTC")
        assert is_quiet_now(qh, datetime(2026, 7, 11, 12, 0)) is True
        assert is_quiet_now(qh, datetime(2026, 7, 11, 18, 0)) is False

    def test_window_wrapping_midnight(self) -> None:
        qh = QuietHoursSettings(enabled=True, start="22:00", end="07:00", timezone="UTC")
        assert is_quiet_now(qh, datetime(2026, 7, 11, 23, 30)) is True
        assert is_quiet_now(qh, datetime(2026, 7, 11, 3, 0)) is True
        assert is_quiet_now(qh, datetime(2026, 7, 11, 12, 0)) is False

    def test_window_respects_timezone(self) -> None:
        # 21:00 UTC is 23:00 in Berlin (summer) — inside a 22:00-07:00 window.
        qh = QuietHoursSettings(enabled=True, start="22:00", end="07:00", timezone="Europe/Berlin")
        assert is_quiet_now(qh, datetime(2026, 7, 11, 21, 0)) is True
        assert is_quiet_now(qh, datetime(2026, 7, 11, 12, 0)) is False

    def test_equal_start_end_treated_as_disabled(self) -> None:
        qh = QuietHoursSettings(enabled=True, start="10:00", end="10:00")
        assert is_quiet_now(qh, datetime(2026, 7, 11, 10, 0)) is False
