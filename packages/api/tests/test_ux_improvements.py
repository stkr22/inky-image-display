"""Tests for curation controls, quiet hours, health states, and list totals."""

from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from inky_image_display_api.mqtt import _record_ack
from inky_image_display_api.services.app_settings_service import is_quiet_now
from inky_image_display_api.services.image_service import get_next_image_for_device, update_display_state
from inky_image_display_shared.models import Device, Image
from inky_image_display_shared.schemas.responses import QuietHoursSettings
from inky_image_display_shared.time import utcnow
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession


async def _add_images(async_engine: AsyncEngine, count: int, **overrides) -> list[Image]:
    images = []
    base = utcnow() - timedelta(days=count)
    async with AsyncSession(async_engine) as session:
        for i in range(count):
            image = Image(
                source_name="manual",
                storage_path=f"manual/{uuid4()}.jpg",
                title=f"img-{i}",
                original_width=1600,
                original_height=1200,
                is_portrait=False,
                last_displayed_at=base + timedelta(hours=i),
                **overrides,
            )
            session.add(image)
            images.append(image)
        await session.commit()
        for image in images:
            await session.refresh(image)
    return images


class TestSelection:
    async def test_excluded_images_never_selected(self, async_engine, seed_device) -> None:
        images = await _add_images(async_engine, 3)
        async with AsyncSession(async_engine) as session:
            for image in images[:2]:
                row = (await session.exec(select(Image).where(col(Image.id) == image.id))).one()
                row.excluded_from_rotation = True
                session.add(row)
            await session.commit()

        async with AsyncSession(async_engine) as session:
            for _ in range(10):
                picked = await get_next_image_for_device(session, seed_device)
                assert picked is not None
                assert picked.id == images[2].id

    async def test_pick_is_among_least_recently_shown_window(self, async_engine, seed_device) -> None:
        images = await _add_images(async_engine, 8)
        oldest_five = {img.id for img in images[:5]}
        async with AsyncSession(async_engine) as session:
            for _ in range(20):
                picked = await get_next_image_for_device(session, seed_device)
                assert picked is not None
                assert picked.id in oldest_five

    async def test_duration_override_beats_device_interval(
        self, async_engine, seed_device, mock_settings: MagicMock
    ) -> None:
        async with AsyncSession(async_engine) as session:
            image = Image(
                source_name="manual",
                storage_path="manual/hold.jpg",
                original_width=1600,
                original_height=1200,
                display_duration_seconds=7200,
            )
            device = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
            session.add(image)
            before = utcnow()
            await update_display_state(session, device, image, mock_settings)

        # Re-read: update_display_state commits, which expires the instance.
        async with AsyncSession(async_engine) as session:
            device = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
            held_until = device.scheduled_next_at
        assert timedelta(seconds=7100) < held_until - before < timedelta(seconds=7300)


class TestQuietHours:
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

    def test_settings_roundtrip_via_api(self, client: TestClient) -> None:
        payload = {"quiet_hours": {"enabled": True, "start": "21:30", "end": "06:45", "timezone": "Europe/Berlin"}}
        response = client.put("/api/app-settings", json=payload)
        assert response.status_code == 200
        fetched = client.get("/api/app-settings").json()
        assert fetched["quiet_hours"]["enabled"] is True
        assert fetched["quiet_hours"]["start"] == "21:30"
        # The other section was left untouched by the partial update.
        assert isinstance(fetched["default_refresh_seconds"], int)

    def test_invalid_timezone_is_rejected(self, client: TestClient) -> None:
        payload = {"quiet_hours": {"enabled": True, "start": "21:30", "end": "06:45", "timezone": "Mars/Olympus"}}
        assert client.put("/api/app-settings", json=payload).status_code == 422


class TestDevicePinAndHealth:
    async def test_patch_pin_and_schedule_exclusion(self, client: TestClient, seed_device) -> None:
        upcoming = client.get("/api/schedule/upcoming").json()
        assert any(entry["name"] == seed_device.device_id for entry in upcoming)

        response = client.patch(f"/api/devices/{seed_device.device_id}", json={"is_pinned": True})
        assert response.status_code == 200
        assert response.json()["is_pinned"] is True

        upcoming = client.get("/api/schedule/upcoming").json()
        assert all(entry["name"] != seed_device.device_id for entry in upcoming)

    @pytest.mark.parametrize(
        ("last_refresh_ok", "error_age_seconds", "expected"),
        [
            (None, None, None),
            (True, None, "ok"),
            (False, 60, "failed_retrying"),
            (False, 3600, "failed_stale"),
        ],
    )
    async def test_refresh_state_classification(  # noqa: PLR0913 — parametrized fixture set
        self,
        client: TestClient,
        async_engine,
        seed_device,
        last_refresh_ok,
        error_age_seconds,
        expected,
    ) -> None:
        async with AsyncSession(async_engine) as session:
            device = (await session.exec(select(Device).where(col(Device.id) == seed_device.id))).one()
            device.last_refresh_ok = last_refresh_ok
            if error_age_seconds is not None:
                device.last_error = "BUSY did not clear"
                device.last_error_at = utcnow() - timedelta(seconds=error_age_seconds)
            session.add(device)
            await session.commit()

        body = client.get(f"/api/devices/{seed_device.device_id}").json()
        assert body["refresh_state"] == expected


class TestFailureNotifications:
    async def test_transitions_fire_notifications_once(
        self, async_engine, seed_device, mock_settings, monkeypatch
    ) -> None:
        sent: list[str] = []
        monkeypatch.setattr(
            "inky_image_display_api.mqtt.notify_in_background",
            lambda _settings, title, _message: sent.append(title),
        )
        mock_settings.notify_url = "https://ntfy.example/inky"

        device_id = seed_device.device_id
        await _record_ack(async_engine, device_id, success=False, error="stuck", settings=mock_settings)
        await _record_ack(async_engine, device_id, success=False, error="stuck", settings=mock_settings)
        await _record_ack(async_engine, device_id, success=True, error=None, settings=mock_settings)
        await _record_ack(async_engine, device_id, success=True, error=None, settings=mock_settings)

        assert len(sent) == 2
        assert "refresh failed" in sent[0]
        assert "recovered" in sent[1]


class TestDisplayFit:
    async def test_exact_mismatch_is_409(self, client: TestClient, async_engine, seed_device, mock_mqtt) -> None:
        mock_mqtt.is_connected = MagicMock(return_value=True)
        async with AsyncSession(async_engine) as session:
            image = Image(
                source_name="manual", storage_path="manual/big.jpg", original_width=4000, original_height=3000
            )
            session.add(image)
            await session.commit()
            await session.refresh(image)

        response = client.post(f"/api/devices/{seed_device.device_id}/display", json={"image_id": str(image.id)})
        assert response.status_code == 409
        assert "fit='auto'" in response.json()["detail"]
        mock_mqtt.send_command.assert_not_called()

    async def test_auto_fit_sends_derived_crop(
        self, client: TestClient, async_engine, seed_device, mock_mqtt, mock_s3_service
    ) -> None:
        mock_mqtt.is_connected = MagicMock(return_value=True)
        async with AsyncSession(async_engine) as session:
            image = Image(
                source_name="manual", storage_path="manual/big.jpg", original_width=4000, original_height=3000
            )
            session.add(image)
            await session.commit()
            await session.refresh(image)

        source = PILImage.new("RGB", (4000, 3000), (10, 120, 200))
        buffer = BytesIO()
        source.save(buffer, format="JPEG")
        mock_s3_service.stat_object = MagicMock(side_effect=FileNotFoundError("no derived yet"))
        mock_s3_service.get_object_bytes = MagicMock(return_value=buffer.getvalue())

        response = client.post(
            f"/api/devices/{seed_device.device_id}/display",
            json={"image_id": str(image.id), "fit": "auto"},
        )
        assert response.status_code == 200
        command = mock_mqtt.send_command.call_args[0][1]
        assert command.image_path == "derived/1600x1200/manual/big.jpg"
        # Derived crop is exactly panel-sized.
        derived_bytes = mock_s3_service.upload_image.call_args[0][1]
        with PILImage.open(BytesIO(derived_bytes)) as derived:
            assert derived.size == (1600, 1200)

    async def test_matching_image_sends_original(self, client: TestClient, seed_device, seed_image, mock_mqtt) -> None:
        mock_mqtt.is_connected = MagicMock(return_value=True)
        response = client.post(f"/api/devices/{seed_device.device_id}/display", json={"image_id": str(seed_image.id)})
        assert response.status_code == 200
        command = mock_mqtt.send_command.call_args[0][1]
        assert command.image_path == seed_image.storage_path


class TestImagesTotalCount:
    async def test_header_reports_filtered_total(self, client: TestClient, async_engine) -> None:
        await _add_images(async_engine, 7)
        response = client.get("/api/images", params={"limit": 3})
        assert len(response.json()) == 3
        assert response.headers["X-Total-Count"] == "7"

    async def test_excluded_filter(self, client: TestClient, async_engine) -> None:
        images = await _add_images(async_engine, 3)
        update = client.put(f"/api/images/{images[0].id}", json={"excluded_from_rotation": True})
        assert update.status_code == 200
        assert update.json()["excluded_from_rotation"] is True

        excluded = client.get("/api/images", params={"excluded": "true"})
        assert [img["id"] for img in excluded.json()] == [str(images[0].id)]
        assert excluded.headers["X-Total-Count"] == "1"
