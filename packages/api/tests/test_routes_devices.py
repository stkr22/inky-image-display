"""Tests for device REST endpoints."""

from unittest.mock import MagicMock

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


class TestRegisterDevice:
    """Tests for POST /api/devices/register."""

    def test_register_creates_device(self, client: TestClient):
        registration = DeviceRegistration(
            device_id="kitchen-display",
            display=DisplayInfo(width=1600, height=1200, orientation="landscape"),
            room="Kitchen",
        )
        resp = client.post("/api/devices/register", json=registration.model_dump(mode="json"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "registered"
        assert body["s3_endpoint"] == "s3.test.local:9000"
        assert body["s3_access_key"] == "reader-key"

    def test_register_updates_existing(self, client: TestClient, seed_device: Device):
        registration = DeviceRegistration(
            device_id=seed_device.device_id,
            display=DisplayInfo(width=1600, height=1200, orientation="landscape"),
            room="Updated Room",
        )
        resp = client.post("/api/devices/register", json=registration.model_dump(mode="json"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"


class TestNextImage:
    """Tests for POST /api/devices/{device_id}/next."""

    def test_not_connected(self, client: TestClient, mock_mqtt: MagicMock, seed_device: Device):
        mock_mqtt.is_connected.return_value = False
        resp = client.post(f"/api/devices/{seed_device.device_id}/next")
        assert resp.status_code == 404

    @pytest.mark.usefixtures("seed_image")
    def test_next_sends_command(
        self,
        client: TestClient,
        mock_mqtt: MagicMock,
        seed_device: Device,
        seed_image: Image,
    ):
        """When connected, selects next image, publishes MQTT command, and returns metadata."""
        mock_mqtt.is_connected.return_value = True

        resp = client.post(f"/api/devices/{seed_device.device_id}/next")
        assert resp.status_code == 200

        body = resp.json()
        assert body["status"] == "ok"
        assert body["image_id"] == str(seed_image.id)
        assert body["title"] == seed_image.title
        assert body["source_name"] == seed_image.source_name

        mock_mqtt.send_command.assert_awaited_once()
        device_id_arg, command_arg = mock_mqtt.send_command.call_args.args
        assert device_id_arg == seed_device.device_id
        assert command_arg.action == "display"
        assert command_arg.image_id == str(seed_image.id)


class TestClearDevice:
    """Tests for POST /api/devices/{device_id}/clear."""

    def test_not_connected(self, client: TestClient, mock_mqtt: MagicMock, seed_device: Device):
        mock_mqtt.is_connected.return_value = False
        resp = client.post(f"/api/devices/{seed_device.device_id}/clear")
        assert resp.status_code == 404

    def test_clear_sends_command(
        self,
        client: TestClient,
        mock_mqtt: MagicMock,
        seed_device: Device,
    ):
        mock_mqtt.is_connected.return_value = True

        resp = client.post(f"/api/devices/{seed_device.device_id}/clear")
        assert resp.status_code == 200

        mock_mqtt.send_command.assert_awaited_once()
        _, command_arg = mock_mqtt.send_command.call_args.args
        assert command_arg.action == "clear"


class TestDisplayCommand:
    """Tests for POST /api/devices/{device_id}/display."""

    def test_not_connected(self, client: TestClient, mock_mqtt: MagicMock, seed_device: Device, seed_image: Image):
        mock_mqtt.is_connected.return_value = False
        resp = client.post(
            f"/api/devices/{seed_device.device_id}/display",
            json={"image_id": str(seed_image.id)},
        )
        assert resp.status_code == 404
