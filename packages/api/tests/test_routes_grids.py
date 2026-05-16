"""Tests for grid REST endpoints."""

from io import BytesIO
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from inky_image_display_shared.models import Device, Image
from PIL import Image as PILImage


def _make_jpeg_bytes(width: int = 1600, height: int = 800) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(64, 96, 128))
    out = BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


class TestGridCrud:
    """Lifecycle: create, list, get, update, delete."""

    def test_create_and_get(self, client: TestClient):
        resp = client.post("/api/grids", json={"name": "kitchen", "width_cm": 80.0, "height_cm": 40.0})
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "kitchen"
        grid_id = body["id"]

        get_resp = client.get(f"/api/grids/{grid_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["width_cm"] == 80.0

    def test_list_empty(self, client: TestClient):
        resp = client.get("/api/grids")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_grid_with_targeted_image(self, client: TestClient, seed_image: Image):
        # Regression: release_grid commits and expires `grid`; subsequent attribute
        # access on `grid.id` used to trigger an async lazy-load → MissingGreenlet.
        grid_resp = client.post("/api/grids", json={"name": "doomed", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_id})

        resp = client.delete(f"/api/grids/{grid_id}")
        assert resp.status_code == 204

        # Targeted image survives, with its grid reference cleared.
        img_resp = client.get(f"/api/images/{seed_image.id}")
        assert img_resp.status_code == 200
        assert img_resp.json()["target_grid_id"] is None


class TestGridDevicePlacement:
    """Add/move/remove devices on a grid."""

    def test_add_device_within_canvas(self, client: TestClient, seed_device: Device):
        grid_resp = client.post("/api/grids", json={"name": "g1", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]

        resp = client.post(
            f"/api/grids/{grid_id}/devices",
            json={"device_id": str(seed_device.id), "bottom_left_x_cm": 0.5, "bottom_left_y_cm": 1.0},
        )
        assert resp.status_code == 201
        placement = resp.json()
        # 13.3" profile is 27.1x20.3 cm; bottom-left (0.5, 1.0) on an 80x40 canvas fits.
        assert placement["width_cm"] > 0
        assert placement["bottom_left_x_cm"] == 0.5
        assert placement["bottom_left_y_cm"] == 1.0

    def test_add_device_overflowing_canvas_rejected(self, client: TestClient, seed_device: Device):
        grid_resp = client.post("/api/grids", json={"name": "g2", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        resp = client.post(
            f"/api/grids/{grid_id}/devices",
            json={"device_id": str(seed_device.id), "bottom_left_x_cm": 60.0, "bottom_left_y_cm": 1.0},
        )
        assert resp.status_code == 400

    def test_duplicate_device_rejected(self, client: TestClient, seed_device: Device):
        grid_resp = client.post("/api/grids", json={"name": "g3", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        body = {"device_id": str(seed_device.id), "bottom_left_x_cm": 0.5, "bottom_left_y_cm": 1.0}
        first = client.post(f"/api/grids/{grid_id}/devices", json=body)
        assert first.status_code == 201
        second = client.post(f"/api/grids/{grid_id}/devices", json=body)
        assert second.status_code == 409

    def test_remove_device(self, client: TestClient, seed_device: Device):
        grid_resp = client.post("/api/grids", json={"name": "g4", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        client.post(
            f"/api/grids/{grid_id}/devices",
            json={"device_id": str(seed_device.id), "bottom_left_x_cm": 0.5, "bottom_left_y_cm": 1.0},
        )
        resp = client.delete(f"/api/grids/{grid_id}/devices/{seed_device.id}")
        assert resp.status_code == 204


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

        grid_resp = client.post("/api/grids", json={"name": "g5", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        client.post(
            f"/api/grids/{grid_id}/devices",
            json={"device_id": str(seed_device.id), "bottom_left_x_cm": 0.5, "bottom_left_y_cm": 1.0},
        )

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
        seed_image: Image,
    ):
        grid_a = client.post("/api/grids", json={"name": "a", "width_cm": 80.0, "height_cm": 40.0}).json()
        grid_b = client.post("/api/grids", json={"name": "b", "width_cm": 80.0, "height_cm": 40.0}).json()
        client.post(
            f"/api/grids/{grid_a['id']}/devices",
            json={"device_id": str(seed_device.id), "bottom_left_x_cm": 0.5, "bottom_left_y_cm": 1.0},
        )
        # Tag the image to grid B, then try to display on A → 400.
        client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_b["id"]})
        resp = client.post(f"/api/grids/{grid_a['id']}/display", json={"image_id": str(seed_image.id)})
        assert resp.status_code == 400


class TestImageRouterTargetGrid:
    """Verify the new ``target_grid_id`` filter and update path."""

    def test_update_sets_target_grid(self, client: TestClient, seed_image: Image):
        grid_resp = client.post("/api/grids", json={"name": "g6", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        resp = client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_id})
        assert resp.status_code == 200
        assert resp.json()["target_grid_id"] == grid_id

    def test_filter_by_target_grid(self, client: TestClient, seed_image: Image):
        grid_resp = client.post("/api/grids", json={"name": "g7", "width_cm": 80.0, "height_cm": 40.0})
        grid_id = grid_resp.json()["id"]
        client.put(f"/api/images/{seed_image.id}", json={"target_grid_id": grid_id})

        resp = client.get("/api/images", params={"target_grid_id": grid_id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
