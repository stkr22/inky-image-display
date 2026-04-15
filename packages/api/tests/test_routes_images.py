"""Tests for image REST endpoints."""

import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_shared.models import Image
from PIL import Image as PILImage


class TestListImages:
    """Tests for GET /api/images."""

    def test_empty_list(self, client: TestClient):
        resp = client.get("/api/images")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_seeded_image(self, client: TestClient, seed_image: Image):
        resp = client.get("/api/images")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == str(seed_image.id)

    @pytest.mark.usefixtures("seed_image")
    def test_filter_by_source_name(self, client: TestClient):
        resp = client.get("/api/images", params={"source_name": "manual"})
        assert len(resp.json()) == 1

        resp = client.get("/api/images", params={"source_name": "immich"})
        assert len(resp.json()) == 0

    @pytest.mark.usefixtures("seed_image")
    def test_filter_by_orientation(self, client: TestClient):
        resp = client.get("/api/images", params={"is_portrait": False})
        assert len(resp.json()) == 1

        resp = client.get("/api/images", params={"is_portrait": True})
        assert len(resp.json()) == 0


class TestGetImage:
    """Tests for GET /api/images/{image_id}."""

    def test_found(self, client: TestClient, seed_image: Image):
        resp = client.get(f"/api/images/{seed_image.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Image"

    def test_not_found(self, client: TestClient):
        resp = client.get("/api/images/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestUploadImage:
    """Tests for POST /api/images."""

    def test_upload_success(self, test_app: FastAPI, client: TestClient):
        buf = io.BytesIO()
        PILImage.new("RGB", (1600, 1200), "red").save(buf, format="JPEG")
        buf.seek(0)

        metadata = json.dumps({"source_name": "test", "title": "Uploaded"})

        resp = client.post(
            "/api/images",
            files={"file": ("test.jpg", buf, "image/jpeg")},
            data={"metadata": metadata},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source_name"] == "test"
        assert data["title"] == "Uploaded"
        assert data["original_width"] == 1600
        assert data["original_height"] == 1200
        assert data["is_portrait"] is False

        # Verify S3 upload was called
        test_app.state.s3_service.upload_image.assert_called_once()


class TestDeleteImage:
    """Tests for DELETE /api/images/{image_id}."""

    def test_delete_success(self, client: TestClient, seed_image: Image):
        resp = client.delete(f"/api/images/{seed_image.id}")
        assert resp.status_code == 204

        # Verify gone
        resp = client.get(f"/api/images/{seed_image.id}")
        assert resp.status_code == 404

    def test_delete_not_found(self, client: TestClient):
        resp = client.delete("/api/images/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
