"""Tests for device REST endpoints."""

import json

import pytest
from fastapi.testclient import TestClient
from inky_image_display_shared.models import Device, Image
from inky_image_display_shared.schemas import DeviceRegistration, DisplayInfo


class TestListDevices:
    """Tests for GET /api/devices."""

    def test_empty(self, client: TestClient):
        resp = client.get("/api/devices")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_seeded(self, client: TestClient, seed_device: Device):
        resp = client.get("/api/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["device_id"] == seed_device.device_id

    @pytest.mark.usefixtures("seed_device")
    def test_filter_by_room(self, client: TestClient):
        resp = client.get("/api/devices", params={"room": "Living Room"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp_none = client.get("/api/devices", params={"room": "Kitchen"})
        assert resp_none.status_code == 200
        assert resp_none.json() == []

    @pytest.mark.usefixtures("seed_device")
    def test_filter_by_is_online(self, client: TestClient):
        resp = client.get("/api/devices", params={"is_online": "true"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp_offline = client.get("/api/devices", params={"is_online": "false"})
        assert resp_offline.status_code == 200
        assert resp_offline.json() == []


class TestGetDevice:
    """Tests for GET /api/devices/{device_id}."""

    def test_found(self, client: TestClient, seed_device: Device):
        resp = client.get(f"/api/devices/{seed_device.device_id}")
        assert resp.status_code == 200
        assert resp.json()["room"] == "Living Room"

    def test_not_found(self, client: TestClient):
        resp = client.get("/api/devices/nonexistent")
        assert resp.status_code == 404


class TestNextImage:
    """Tests for POST /api/devices/{device_id}/next."""

    def test_not_connected(self, client: TestClient, seed_device: Device):
        """Returns 404 when device is not connected via WebSocket."""
        resp = client.post(f"/api/devices/{seed_device.device_id}/next")
        assert resp.status_code == 404

    @pytest.mark.usefixtures("seed_image")
    def test_next_sends_command(
        self,
        client: TestClient,
        seed_device: Device,
        seed_image: Image,
    ):
        """When connected, selects next image, sends WebSocket command, and returns metadata."""
        registration = DeviceRegistration(
            device_id=seed_device.device_id,
            display=DisplayInfo(width=1600, height=1200),
        )
        with client.websocket_connect(f"/ws/devices/{seed_device.device_id}") as ws:
            ws.send_text(registration.model_dump_json())
            ws.receive_text()  # consume registration response

            resp = client.post(f"/api/devices/{seed_device.device_id}/next")
            assert resp.status_code == 200

            body = resp.json()
            assert body["status"] == "ok"
            assert body["image_id"] == str(seed_image.id)
            assert body["title"] == seed_image.title
            assert body["source_name"] == seed_image.source_name

            # The device should receive the display command via WebSocket
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["action"] == "display"
            assert data["image_id"] == str(seed_image.id)


class TestClearDevice:
    """Tests for POST /api/devices/{device_id}/clear."""

    def test_not_connected(self, client: TestClient, seed_device: Device):
        resp = client.post(f"/api/devices/{seed_device.device_id}/clear")
        assert resp.status_code == 404

    def test_clear_sends_command(
        self,
        client: TestClient,
        seed_device: Device,
    ):
        """Sends clear command to connected device."""
        registration = DeviceRegistration(
            device_id=seed_device.device_id,
            display=DisplayInfo(width=1600, height=1200),
        )
        with client.websocket_connect(f"/ws/devices/{seed_device.device_id}") as ws:
            ws.send_text(registration.model_dump_json())
            ws.receive_text()

            resp = client.post(f"/api/devices/{seed_device.device_id}/clear")
            assert resp.status_code == 200

            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["action"] == "clear"
