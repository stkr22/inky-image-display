"""Route-level tests for /api/motd."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient
    from inky_image_display_shared.models import Device


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
