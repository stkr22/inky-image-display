"""Tests for grid REST endpoints (tile-layout based)."""

from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from inky_image_display_shared.models import Device, DeviceProfile, Image
from PIL import Image as PILImage
from sqlmodel.ext.asyncio.session import AsyncSession


def _make_jpeg_bytes(width: int = 1600, height: int = 800) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(64, 96, 128))
    out = BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


@pytest.fixture
async def second_device(async_engine, seed_profile: DeviceProfile) -> Device:
    """A second landscape device on the same 27.1x20.3 cm profile."""
    device = Device(
        id=uuid4(),
        device_id="test-display-2",
        room="Kitchen",
        device_profile_id=seed_profile.id,
        display_orientation="landscape",
        is_online=True,
        last_seen=datetime.now(),
    )
    async with AsyncSession(async_engine) as session:
        session.add(device)
        await session.commit()
        await session.refresh(device)
    return device


class TestGridCrud:
    """Lifecycle: create from a layout, list, get, update, delete."""

    def test_create_computes_canvas_and_placement(self, client: TestClient, seed_device: Device):
        resp = client.post("/api/grids", json={"name": "kitchen", "rows": [[str(seed_device.id)]]})
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "kitchen"
        # Canvas dims equal the single panel's physical dims (27.1x20.3, landscape).
        assert body["width_cm"] == pytest.approx(27.1)
        assert body["height_cm"] == pytest.approx(20.3)
        placement = body["devices"][0]
        assert placement["row"] == 0
        assert placement["col"] == 0
        assert placement["bottom_left_x_cm"] == pytest.approx(0.0)
        assert placement["bottom_left_y_cm"] == pytest.approx(0.0)

    def test_create_two_wide_layout(self, client: TestClient, seed_device: Device, second_device: Device):
        resp = client.post(
            "/api/grids",
            json={"name": "wall", "rows": [[str(seed_device.id), str(second_device.id)]]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["width_cm"] == pytest.approx(2 * 27.1)
        assert body["height_cm"] == pytest.approx(20.3)
        by_col = {p["col"]: p for p in body["devices"]}
        assert by_col[1]["bottom_left_x_cm"] == pytest.approx(27.1)

    def test_create_stacked_layout(self, client: TestClient, seed_device: Device, second_device: Device):
        resp = client.post(
            "/api/grids",
            json={"name": "tower", "rows": [[str(seed_device.id)], [str(second_device.id)]]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["height_cm"] == pytest.approx(2 * 20.3)
        by_row = {p["row"]: p for p in body["devices"]}
        # Row 0 is the top row → highest bottom-left Y.
        assert by_row[0]["bottom_left_y_cm"] == pytest.approx(20.3)
        assert by_row[1]["bottom_left_y_cm"] == pytest.approx(0.0)

    def test_create_requires_devices(self, client: TestClient):
        assert client.post("/api/grids", json={"name": "empty", "rows": []}).status_code == 422
        assert client.post("/api/grids", json={"name": "empty-row", "rows": [[]]}).status_code == 422

    def test_duplicate_device_in_layout_rejected(self, client: TestClient, seed_device: Device):
        resp = client.post(
            "/api/grids",
            json={"name": "dup", "rows": [[str(seed_device.id), str(seed_device.id)]]},
        )
        assert resp.status_code == 400

    def test_device_in_another_grid_rejected(self, client: TestClient, seed_device: Device):
        first = client.post("/api/grids", json={"name": "first", "rows": [[str(seed_device.id)]]})
        assert first.status_code == 201
        second = client.post("/api/grids", json={"name": "second", "rows": [[str(seed_device.id)]]})
        assert second.status_code == 409

    def test_update_replaces_layout(self, client: TestClient, seed_device: Device, second_device: Device):
        grid_id = client.post("/api/grids", json={"name": "g", "rows": [[str(seed_device.id)]]}).json()["id"]

        resp = client.put(
            f"/api/grids/{grid_id}",
            json={"rows": [[str(seed_device.id), str(second_device.id)]]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["width_cm"] == pytest.approx(2 * 27.1)
        assert len(body["devices"]) == 2

        # Dropping a device from the layout removes its placement.
        resp = client.put(f"/api/grids/{grid_id}", json={"rows": [[str(second_device.id)]]})
        assert [p["device_id"] for p in resp.json()["devices"]] == [str(second_device.id)]

    def test_list_empty(self, client: TestClient):
        resp = client.get("/api/grids")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_grid_with_targeted_image(self, client: TestClient, seed_device: Device, seed_image: Image):
        # Regression: release_grid commits and expires `grid`; subsequent attribute
        # access on `grid.id` used to trigger an async lazy-load → MissingGreenlet.
        grid_resp = client.post("/api/grids", json={"name": "doomed", "rows": [[str(seed_device.id)]]})
        grid_id = grid_resp.json()["id"]
        client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_id})

        resp = client.delete(f"/api/grids/{grid_id}")
        assert resp.status_code == 204

        # Targeted image survives, with its grid reference cleared.
        img_resp = client.get(f"/api/images/{seed_image.id}")
        assert img_resp.status_code == 200
        assert img_resp.json()["target_grid_id"] is None


class TestGridDisplay:
    """End-to-end display path: render crop, claim device, push MQTT."""

    def test_display_pushes_and_claims(
        self,
        client: TestClient,
        seed_device: Device,
        seed_image: Image,
        mock_s3_service: MagicMock,
        mock_mqtt: MagicMock,
    ):
        # Source image bytes returned by the s3 fetch.
        mock_response = MagicMock()
        mock_response.read.return_value = _make_jpeg_bytes()
        mock_s3_service._client.get_object.return_value = mock_response
        mock_s3_service._bucket = "test-images"
        mock_mqtt.is_connected.return_value = True

        grid_resp = client.post("/api/grids", json={"name": "g5", "rows": [[str(seed_device.id)]]})
        grid_id = grid_resp.json()["id"]

        resp = client.post(f"/api/grids/{grid_id}/display", json={"image_id": str(seed_image.id)})
        assert resp.status_code == 200

        # Crop uploaded under grids/{grid_id}/{image_id}/{device_id}.jpg.
        assert mock_s3_service.upload_image.called
        uploaded_path = mock_s3_service.upload_image.call_args[0][0]
        assert uploaded_path.startswith(f"grids/{grid_id}/{seed_image.id}/")

        # MQTT command went out.
        assert mock_mqtt.send_command.called

    def test_display_rejects_wrong_grid_target(
        self,
        client: TestClient,
        seed_device: Device,
        second_device: Device,
        seed_image: Image,
    ):
        grid_a = client.post("/api/grids", json={"name": "a", "rows": [[str(seed_device.id)]]}).json()
        grid_b = client.post("/api/grids", json={"name": "b", "rows": [[str(second_device.id)]]}).json()
        # Tag the image to grid B, then try to display on A → 400.
        client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_b["id"]})
        resp = client.post(f"/api/grids/{grid_a['id']}/display", json={"image_id": str(seed_image.id)})
        assert resp.status_code == 400


class TestImageRouterTargetGrid:
    """Verify the ``target_grid_id`` filter and update path."""

    def test_update_sets_target_grid(self, client: TestClient, seed_device: Device, seed_image: Image):
        grid_resp = client.post("/api/grids", json={"name": "g6", "rows": [[str(seed_device.id)]]})
        grid_id = grid_resp.json()["id"]
        resp = client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_id})
        assert resp.status_code == 200
        assert resp.json()["target_grid_id"] == grid_id

    def test_filter_by_target_grid(self, client: TestClient, seed_device: Device, seed_image: Image):
        grid_resp = client.post("/api/grids", json={"name": "g7", "rows": [[str(seed_device.id)]]})
        grid_id = grid_resp.json()["id"]
        client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_id})

        resp = client.get("/api/images", params={"target_grid_id": grid_id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
