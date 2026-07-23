"""Tests for the operator-tunable app settings (key/value table + routes).

Covers the fallback to env-loaded ``Settings.default_display_duration``
when the row is absent, round-trip persistence via the service helpers,
and the public ``GET``/``PUT /api/app-settings`` endpoints used by the UI.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from inky_image_display_api.services.app_settings_service import (
    DEFAULT_REFRESH_SECONDS_KEY,
    get_default_refresh_seconds,
    set_default_refresh_seconds,
)
from inky_image_display_shared.models import AppSetting
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncEngine


class TestGetDefaultRefreshSeconds:
    """Branches not reachable through the routes: corrupted rows."""

    async def test_corrupted_value_falls_back(self, async_engine: AsyncEngine):
        # A garbled row should not take down the rotation loop — we treat
        # it as "no override" rather than raising.
        settings = MagicMock(default_display_duration=1234)
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
        mock_settings: MagicMock,
    ):
        resp = client.get("/api/app-settings")
        assert resp.status_code == 200
        assert resp.json()["default_refresh_seconds"] == mock_settings.default_display_duration

    def test_put_persists_and_get_reflects(self, client: TestClient):
        resp = client.put("/api/app-settings", json={"default_refresh_seconds": 1800})
        assert resp.status_code == 200
        assert resp.json()["default_refresh_seconds"] == 1800

        resp = client.get("/api/app-settings")
        assert resp.status_code == 200
        assert resp.json()["default_refresh_seconds"] == 1800

    def test_put_rejects_out_of_range(self, client: TestClient):
        resp = client.put("/api/app-settings", json={"default_refresh_seconds": 0})
        assert resp.status_code == 422
        resp = client.put("/api/app-settings", json={"default_refresh_seconds": 7 * 24 * 3600 + 1})
        assert resp.status_code == 422

    def test_stagger_rotation_defaults_on_and_round_trips(self, client: TestClient):
        assert client.get("/api/app-settings").json()["stagger_rotation"] is True

        resp = client.put("/api/app-settings", json={"stagger_rotation": False})
        assert resp.status_code == 200
        assert resp.json()["stagger_rotation"] is False
        assert client.get("/api/app-settings").json()["stagger_rotation"] is False
