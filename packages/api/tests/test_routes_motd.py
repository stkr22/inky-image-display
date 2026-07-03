"""Route-level tests for /api/motd."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from inky_image_display_shared.models import MotdMessage, MotdScreen
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from inky_image_display_shared.models import Device
    from sqlalchemy.ext.asyncio import AsyncEngine


class TestMotdConfig:
    def test_get_creates_singleton_with_default_prompt(self, client: TestClient) -> None:
        response = client.get("/api/motd/config")
        assert response.status_code == 200
        body = response.json()
        assert body["content_prompt"] == DEFAULT_MOTD_PROMPT
        assert body["default_prompt"] == DEFAULT_MOTD_PROMPT
        assert body["assignments"] == []
        # Second call returns the same row, not a new one.
        assert client.get("/api/motd/config").json()["id"] == body["id"]

    def test_put_round_trip_with_assignments(self, client: TestClient, seed_device: Device) -> None:
        payload = {
            "content_prompt": "Custom themes",
            "source_mode": "knowledge",
            "schedule_enabled": True,
            "display_time": "07:30",
            "weekday_mask": 31,
            "timezone": "Europe/Berlin",
            "generation_lead_minutes": 45,
            "display_duration_seconds": 3600,
            "assignments": [{"device_id": str(seed_device.id), "parts": ["what", "why+takeaway", "qr"]}],
        }
        response = client.put("/api/motd/config", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["content_prompt"] == "Custom themes"
        assert body["source_mode"] == "knowledge"
        assert body["display_time"] == "07:30"
        assert body["timezone"] == "Europe/Berlin"
        assert body["display_duration_seconds"] == 3600
        assert body["assignments"] == [
            {"device_id": str(seed_device.id), "parts": ["what", "why+takeaway", "qr"], "rotation_index": 0}
        ]

    def test_put_clear_duration_sets_indefinite(self, client: TestClient) -> None:
        client.put("/api/motd/config", json={"display_duration_seconds": 600})
        response = client.put("/api/motd/config", json={"clear_display_duration": True})
        assert response.json()["display_duration_seconds"] is None

    def test_put_rejects_invalid_part(self, client: TestClient, seed_device: Device) -> None:
        response = client.put(
            "/api/motd/config",
            json={"assignments": [{"device_id": str(seed_device.id), "parts": ["what", "banana"]}]},
        )
        assert response.status_code == 422
        assert "banana" in response.text

    def test_put_rejects_non_text_compound(self, client: TestClient, seed_device: Device) -> None:
        response = client.put(
            "/api/motd/config",
            json={"assignments": [{"device_id": str(seed_device.id), "parts": ["image+qr"]}]},
        )
        assert response.status_code == 422

    def test_put_rejects_bad_timezone_and_time(self, client: TestClient) -> None:
        assert client.put("/api/motd/config", json={"timezone": "Mars/Olympus"}).status_code == 422
        assert client.put("/api/motd/config", json={"display_time": "25:00"}).status_code == 422

    @pytest.mark.asyncio
    async def test_put_assignments_resync_active_session(
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        mock_mqtt: MagicMock,
        mock_s3_service: MagicMock,
        seed_device: Device,
    ) -> None:
        """Assignment edits made while a session is active take effect immediately."""
        mock_mqtt.is_connected = MagicMock(return_value=True)
        config_id = client.get("/api/motd/config").json()["id"]
        client.put(
            "/api/motd/config",
            json={"assignments": [{"device_id": str(seed_device.id), "parts": ["what"]}]},
        )
        async with AsyncSession(async_engine) as session:
            message = MotdMessage(
                config_id=UUID(config_id),
                status="ready",
                headline="Bridge built",
                what="A bridge.",
                takeaway="Build bridges.",
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            session.add(
                MotdScreen(
                    message_id=message.id,
                    part="what",
                    width=1600,
                    height=1200,
                    is_portrait=False,
                    storage_path=f"motd/{message.id}/what_1600x1200.jpg",
                )
            )
            await session.commit()
        assert client.post("/api/motd/display").status_code == 200
        assert mock_mqtt.send_command.await_count == 1

        response = client.put(
            "/api/motd/config",
            json={"assignments": [{"device_id": str(seed_device.id), "parts": ["takeaway"]}]},
        )

        assert response.status_code == 200
        # The takeaway screen did not exist — rendered on demand and pushed.
        assert mock_mqtt.send_command.await_count == 2
        command = mock_mqtt.send_command.await_args.args[1]
        assert command.image_path.endswith("takeaway_1600x1200.jpg")
        mock_s3_service.upload_image.assert_called_once()
        status = client.get("/api/motd/status").json()
        assert status["devices"][0]["current_part"] == "takeaway"

    def test_put_rejects_unknown_device(self, client: TestClient) -> None:
        response = client.put(
            "/api/motd/config",
            json={"assignments": [{"device_id": "00000000-0000-0000-0000-000000000001", "parts": ["what"]}]},
        )
        assert response.status_code == 404


class TestMotdActions:
    def test_generate_without_api_key_returns_503(self, client: TestClient, mock_settings: MagicMock) -> None:
        mock_settings.gemini_api_key = None
        response = client.post("/api/motd/generate")
        assert response.status_code == 503

    def test_display_without_message_returns_409(self, client: TestClient, seed_device: Device) -> None:
        client.put(
            "/api/motd/config",
            json={"assignments": [{"device_id": str(seed_device.id), "parts": ["what"]}]},
        )
        response = client.post("/api/motd/display")
        assert response.status_code == 409
        assert "No generated message" in response.json()["detail"]

    def test_display_unknown_message_returns_409(self, client: TestClient) -> None:
        response = client.post("/api/motd/display", json={"message_id": "00000000-0000-0000-0000-000000000001"})
        assert response.status_code == 409
        assert "no longer exists" in response.json()["detail"]

    def test_release_is_idempotent(self, client: TestClient) -> None:
        response = client.post("/api/motd/release")
        assert response.status_code == 200
        assert response.json() == {"status": "released"}

    def test_status_inactive(self, client: TestClient) -> None:
        response = client.get("/api/motd/status")
        assert response.status_code == 200
        body = response.json()
        assert body["active"] is False
        assert body["devices"] == []

    def test_latest_message_null_when_none(self, client: TestClient) -> None:
        response = client.get("/api/motd/messages/latest")
        assert response.status_code == 200
        assert response.json() is None

    def test_messages_list_empty(self, client: TestClient) -> None:
        response = client.get("/api/motd/messages")
        assert response.status_code == 200
        assert response.json() == []
