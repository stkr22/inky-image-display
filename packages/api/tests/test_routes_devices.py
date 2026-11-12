"""Tests for device REST endpoints."""

from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import aiomqtt
import pytest
from fastapi.testclient import TestClient
from inky_image_display_shared.models import Device, Image
from inky_image_display_shared.schemas import DeviceRegistration
from inky_image_display_shared.time import utcnow
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession


class TestListDevices:
    """Tests for GET /api/devices."""

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

    @pytest.mark.usefixtures("seed_profile")
    def test_register_creates_device(self, client: TestClient):
        registration = DeviceRegistration(
            device_id="kitchen-display",
            device_profile_key="inky_impression_13_spectra6",
            orientation="landscape",
            room="Kitchen",
        )
        resp = client.post("/api/devices/register", json=registration.model_dump(mode="json"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "registered"
        # Controllers get the device-facing endpoint, not the API's own.
        assert body["s3_endpoint"] == "s3.public.test"
        assert body["s3_secure"] is True
        assert body["s3_access_key"] == "reader-key"

    def test_register_rejects_unknown_profile(self, client: TestClient):
        registration = DeviceRegistration(
            device_id="some-display",
            device_profile_key="does_not_exist",
            orientation="landscape",
        )
        resp = client.post("/api/devices/register", json=registration.model_dump(mode="json"))
        assert resp.status_code == 400

    def test_register_updates_existing(self, client: TestClient, seed_device: Device):
        registration = DeviceRegistration(
            device_id=seed_device.device_id,
            device_profile_key="inky_impression_13_spectra6",
            orientation="landscape",
            room="Updated Room",
        )
        resp = client.post("/api/devices/register", json=registration.model_dump(mode="json"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"


class TestNextImage:
    """Tests for POST /api/devices/{device_id}/next."""

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

    @pytest.fixture(autouse=True)
    def connected(self, mock_mqtt: MagicMock) -> None:
        mock_mqtt.is_connected.return_value = True

    async def _big_image(self, async_engine: AsyncEngine) -> Image:
        async with AsyncSession(async_engine) as session:
            image = Image(
                source_name="manual", storage_path="manual/big.jpg", original_width=4000, original_height=3000
            )
            session.add(image)
            await session.commit()
            await session.refresh(image)
        return image

    async def test_exact_mismatch_is_409(
        self, client: TestClient, async_engine: AsyncEngine, seed_device: Device, mock_mqtt: MagicMock
    ) -> None:
        image = await self._big_image(async_engine)
        response = client.post(f"/api/devices/{seed_device.device_id}/display", json={"image_id": str(image.id)})
        assert response.status_code == 409
        assert "fit='auto'" in response.json()["detail"]
        mock_mqtt.send_command.assert_not_called()

    async def test_auto_fit_sends_derived_crop(
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        seed_device: Device,
        mock_mqtt: MagicMock,
        mock_s3_service: MagicMock,
    ) -> None:
        image = await self._big_image(async_engine)
        buffer = BytesIO()
        PILImage.new("RGB", (4000, 3000), (10, 120, 200)).save(buffer, format="JPEG")
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

    def test_matching_image_sends_original(
        self, client: TestClient, seed_device: Device, seed_image: Image, mock_mqtt: MagicMock
    ) -> None:
        response = client.post(f"/api/devices/{seed_device.device_id}/display", json={"image_id": str(seed_image.id)})
        assert response.status_code == 200
        command = mock_mqtt.send_command.call_args[0][1]
        assert command.image_path == seed_image.storage_path


@pytest.mark.parametrize("endpoint", ["next", "clear", "display"])
def test_command_to_disconnected_device_is_404(
    client: TestClient, mock_mqtt: MagicMock, seed_device: Device, seed_image: Image, endpoint: str
) -> None:
    mock_mqtt.is_connected.return_value = False
    body = {"image_id": str(seed_image.id)} if endpoint == "display" else None
    resp = client.post(f"/api/devices/{seed_device.device_id}/{endpoint}", json=body)
    assert resp.status_code == 404
    mock_mqtt.send_command.assert_not_called()


class TestPinAndHealth:
    """Pinning holds a device out of rotation; refresh_state summarises its last acks."""

    def test_patch_pin_and_schedule_exclusion(self, client: TestClient, seed_device: Device) -> None:
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
    async def test_refresh_state_classification(  # noqa: PLR0913, PLR0917 — parametrized fixture set
        self,
        client: TestClient,
        async_engine: AsyncEngine,
        seed_device: Device,
        last_refresh_ok: bool | None,
        error_age_seconds: int | None,
        expected: str | None,
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


class TestCurrentImageEmbed:
    """DeviceResponse embeds a summary of the currently displayed image."""

    @pytest.fixture
    async def device_with_image(self, async_engine: AsyncEngine, seed_device: Device, seed_image: Image) -> Device:
        """Point the seeded device at the seeded image."""
        async with AsyncSession(async_engine) as session:
            result = await session.exec(select(Device).where(col(Device.id) == seed_device.id))
            device = result.one()
            device.current_image_id = seed_image.id
            session.add(device)
            await session.commit()
        return seed_device

    @pytest.mark.usefixtures("device_with_image")
    def test_list_and_get_embed_current_image(self, client: TestClient, seed_device: Device, seed_image: Image):
        resp = client.get("/api/devices")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["current_image"] == {
            "id": str(seed_image.id),
            "storage_path": seed_image.storage_path,
            "title": seed_image.title,
        }

        resp = client.get(f"/api/devices/{seed_device.device_id}")
        assert resp.json()["current_image"]["id"] == str(seed_image.id)

    def test_no_current_image_is_null(self, client: TestClient, seed_device: Device):
        resp = client.get(f"/api/devices/{seed_device.device_id}")
        assert resp.json()["current_image"] is None


class TestSendFailures:
    """A device dropping or the broker vanishing mid-request is a retryable 503."""

    @pytest.mark.parametrize(
        "error",
        [KeyError("test-display"), RuntimeError("MQTT client is not connected"), aiomqtt.MqttError("gone")],
    )
    @pytest.mark.parametrize("endpoint", ["clear", "next", "display"])
    def test_transport_failure_is_503(  # noqa: PLR0913, PLR0917
        self,
        client: TestClient,
        seed_device: Device,
        seed_image: Image,
        mock_mqtt: MagicMock,
        error: Exception,
        endpoint: str,
    ) -> None:
        mock_mqtt.is_connected = MagicMock(return_value=True)
        mock_mqtt.send_command = AsyncMock(side_effect=error)
        body = {"image_id": str(seed_image.id)} if endpoint == "display" else None
        response = client.post(f"/api/devices/{seed_device.device_id}/{endpoint}", json=body)
        assert response.status_code == 503


def test_registration_returns_plain_secrets_on_the_wire(client: TestClient, seed_profile) -> None:
    response = client.post(
        "/api/devices/register",
        json={"device_id": "new-panel", "device_profile_key": seed_profile.key, "orientation": "landscape"},
    )
    assert response.status_code == 200
    assert response.json()["s3_secret_key"] == "reader-secret"
