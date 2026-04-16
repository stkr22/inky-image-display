"""Tests for image REST endpoints."""

import io
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_shared.models import Image
from PIL import Image as PILImage
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession


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


@pytest.fixture
async def seed_immich_image(async_engine: AsyncEngine) -> Image:
    """Insert an Immich-sourced image with source_url and expires_at."""
    image = Image(
        id=uuid4(),
        source_name="test-job",
        storage_path="immich/abc123.jpg",
        source_url="immich://abc123",
        title="Immich Photo",
        original_width=1600,
        original_height=1200,
        is_portrait=False,
        expires_at=datetime.now() - timedelta(days=1),
    )
    async with AsyncSession(async_engine) as session:
        session.add(image)
        await session.commit()
        await session.refresh(image)
    return image


class TestListImagesFilters:
    """Tests for new filter params on GET /api/images."""

    def test_filter_by_source_url(self, client: TestClient, seed_immich_image: Image):
        resp = client.get("/api/images", params={"source_url": "immich://abc123"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["source_url"] == "immich://abc123"

    def test_filter_by_source_url_no_match(self, client: TestClient, seed_immich_image: Image):
        resp = client.get("/api/images", params={"source_url": "immich://other"})
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_filter_by_source_url_prefix(self, client: TestClient, seed_immich_image: Image):
        resp = client.get("/api/images", params={"source_url_prefix": "immich://"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_filter_by_expires_before(self, client: TestClient, seed_immich_image: Image):
        resp = client.get("/api/images", params={"expires_before": datetime.now().isoformat()})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_expires_before_excludes_future(self, client: TestClient, seed_immich_image: Image):
        past = (datetime.now() - timedelta(days=2)).isoformat()
        resp = client.get("/api/images", params={"expires_before": past})
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_response_includes_source_url_and_expires_at(self, client: TestClient, seed_immich_image: Image):
        resp = client.get("/api/images")
        assert resp.status_code == 200
        data = resp.json()[0]
        assert "source_url" in data
        assert "expires_at" in data


class TestRegisterImage:
    """Tests for POST /api/images/register."""

    def test_register_success(self, client: TestClient):
        payload = {
            "source_name": "immich",
            "storage_path": "immich/asset123.jpg",
            "source_url": "immich://asset123",
            "title": "A synced photo",
            "original_width": 1600,
            "original_height": 1200,
            "is_portrait": False,
        }
        resp = client.post("/api/images/register", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["storage_path"] == "immich/asset123.jpg"
        assert data["source_url"] == "immich://asset123"
        assert data["title"] == "A synced photo"

    def test_register_does_not_call_s3(self, test_app: FastAPI, client: TestClient):
        payload = {"storage_path": "immich/x.jpg"}
        client.post("/api/images/register", json=payload)
        test_app.state.s3_service.upload_image.assert_not_called()

    def test_register_with_expires_at(self, client: TestClient):
        future = (datetime.now() + timedelta(days=7)).isoformat()
        resp = client.post(
            "/api/images/register",
            json={"storage_path": "immich/y.jpg", "expires_at": future},
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is not None


class TestUpdateImage:
    """Tests for PUT /api/images/{image_id}."""

    def test_update_title(self, client: TestClient, seed_image: Image):
        resp = client.put(f"/api/images/{seed_image.id}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_partial_update_preserves_other_fields(self, client: TestClient, seed_image: Image):
        resp = client.put(f"/api/images/{seed_image.id}", json={"title": "Updated"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_name"] == seed_image.source_name
        assert data["storage_path"] == seed_image.storage_path

    def test_update_not_found(self, client: TestClient):
        resp = client.put(
            "/api/images/00000000-0000-0000-0000-000000000000",
            json={"title": "Ghost"},
        )
        assert resp.status_code == 404
