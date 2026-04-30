"""Tests for the WebSocket device communication endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from inky_image_display_api.websocket import ConnectionManager
from inky_image_display_shared.models import Device
from inky_image_display_shared.schemas import (
    DeviceRegistration,
    DisplayInfo,
    RegistrationResponse,
)


class TestConnectionManager:
    """Tests for the ConnectionManager."""

    def test_is_connected_false_when_empty(self, connection_manager):
        assert connection_manager.is_connected("nonexistent") is False

    def test_connected_device_ids_empty(self, connection_manager):
        assert connection_manager.connected_device_ids() == []

    @pytest.mark.asyncio
    async def test_connect_replaces_without_kicking_previous(self, connection_manager):
        """A new connection takes the registry slot but does NOT close the old socket.

        Proactively closing the previous caused dueling-client deployments
        (two processes accidentally sharing a device_id) to ping-pong each
        other off every few seconds — each new connection would 1012-close
        the other, which would reconnect and 1012-close back. Last-write-
        wins on the registry plus identity-checked disconnect handles the
        stale-finally race without triggering that loop.
        """
        old = MagicMock()
        old.accept = AsyncMock()
        old.close = AsyncMock()
        new = MagicMock()
        new.accept = AsyncMock()
        new.close = AsyncMock()

        await connection_manager.connect("dev-1", old)
        await connection_manager.connect("dev-1", new)

        old.close.assert_not_awaited()
        assert connection_manager.connected_device_ids() == ["dev-1"]

    @pytest.mark.asyncio
    async def test_disconnect_only_pops_matching_socket(self, connection_manager):
        """Stale finally-block must NOT evict a newer live connection.

        This is the race that left controller-2 visible as offline:
        old socket's TCP finally died long after the reconnect, and its
        ``disconnect`` was clobbering the new socket's registry entry.
        """
        old = MagicMock()
        old.accept = AsyncMock()
        old.close = AsyncMock()
        new = MagicMock()
        new.accept = AsyncMock()
        new.close = AsyncMock()

        await connection_manager.connect("dev-1", old)
        await connection_manager.connect("dev-1", new)

        # The old handler's finally-block runs *after* the reconnect.
        was_active = connection_manager.disconnect("dev-1", old)

        assert was_active is False
        assert connection_manager.is_connected("dev-1") is True

        # The live socket eventually disconnects normally.
        assert connection_manager.disconnect("dev-1", new) is True
        assert connection_manager.is_connected("dev-1") is False


class TestDeviceWebSocket:
    """Tests for the /ws/devices/{device_id} endpoint."""

    def test_registration_creates_device(self, client: TestClient):
        """A new device is created when it registers for the first time."""
        registration = DeviceRegistration(
            device_id="kitchen-display",
            display=DisplayInfo(width=1600, height=1200, orientation="landscape"),
            room="Kitchen",
        )

        with client.websocket_connect("/ws/devices/kitchen-display") as ws:
            ws.send_text(registration.model_dump_json())
            raw = ws.receive_text()
            response = RegistrationResponse.model_validate_json(raw)

            assert response.status == "registered"
            assert response.s3_endpoint == "s3.test.local:9000"
            assert response.s3_bucket == "test-images"
            assert response.s3_access_key == "reader-key"
            assert response.s3_secret_key == "reader-secret"

    def test_registration_updates_existing_device(self, client: TestClient, seed_device: Device):
        """An existing device is updated on re-registration."""
        registration = DeviceRegistration(
            device_id=seed_device.device_id,
            display=DisplayInfo(width=1600, height=1200, orientation="landscape"),
            room="Updated Room",
        )

        with client.websocket_connect(f"/ws/devices/{seed_device.device_id}") as ws:
            ws.send_text(registration.model_dump_json())
            raw = ws.receive_text()
            response = RegistrationResponse.model_validate_json(raw)

            assert response.status == "updated"

    def test_device_marked_offline_on_disconnect(
        self,
        client: TestClient,
        connection_manager: ConnectionManager,
    ):
        """Device is removed from ConnectionManager when the WebSocket closes."""
        registration = DeviceRegistration(
            device_id="temp-device",
            display=DisplayInfo(),
        )

        with client.websocket_connect("/ws/devices/temp-device") as ws:
            ws.send_text(registration.model_dump_json())
            ws.receive_text()  # consume registration response
            assert connection_manager.is_connected("temp-device")

        # After context manager exits, device should be disconnected
        assert not connection_manager.is_connected("temp-device")

    def test_acknowledge_parsed(self, client: TestClient):
        """Server parses DeviceAcknowledge messages without error."""
        registration = DeviceRegistration(device_id="ack-device", display=DisplayInfo())
        ack_payload = json.dumps(
            {
                "device_id": "ack-device",
                "image_id": "abc-123",
                "successful_display_change": True,
                "error": None,
            }
        )

        with client.websocket_connect("/ws/devices/ack-device") as ws:
            ws.send_text(registration.model_dump_json())
            ws.receive_text()
            # Send ack — server logs it but doesn't respond
            ws.send_text(ack_payload)
