"""Upload validation, list pagination and full image deletion.

Uploads come from browsers and scripts alike, so bad input must be a clean
4xx rather than a 500 — and deleting an image must take everything derived
from it along, whichever path deletes it.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from inky_image_display_shared.models import Device, DeviceProfile, Grid, Image, ImageBook, ImageGroup
from PIL import Image as PILImage
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from inky_image_display_api.config import Settings
    from sqlalchemy.ext.asyncio import AsyncEngine


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (40, 30), "red").save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(client: TestClient, data: bytes, metadata: str = "{}"):
    return client.post("/api/images", files={"file": ("x.jpg", data, "image/jpeg")}, data={"metadata": metadata})


class TestUploadValidation:
    def test_malformed_metadata_json_is_422(self, client: TestClient, mock_s3_service: MagicMock) -> None:
        assert _upload(client, _jpeg(), "{not json").status_code == 422
        mock_s3_service.upload_image.assert_not_called()

    def test_invalid_metadata_field_is_422(self, client: TestClient) -> None:
        assert _upload(client, _jpeg(), json.dumps({"display_duration_seconds": "soon"})).status_code == 422

    def test_non_image_is_422_and_not_stored(self, client: TestClient, mock_s3_service: MagicMock) -> None:
        assert _upload(client, b"definitely not an image").status_code == 422
        mock_s3_service.upload_image.assert_not_called()

    def test_oversized_upload_is_413(self, client: TestClient, settings: Settings) -> None:
        settings.max_upload_bytes = 100
        assert _upload(client, _jpeg()).status_code == 413

    @pytest.mark.parametrize("source_name", ["thumbs", "derived", "grids", "../escape", "a/b", "", "UPPER"])
    def test_unsafe_or_reserved_source_name_is_422(self, client: TestClient, source_name: str) -> None:
        response = _upload(client, _jpeg(), json.dumps({"source_name": source_name}))
        assert response.status_code == 422

    def test_valid_upload_stores_under_source_prefix(self, client: TestClient, mock_s3_service: MagicMock) -> None:
        response = _upload(client, _jpeg(), json.dumps({"source_name": "my-camera"}))
        assert response.status_code == 201
        assert response.json()["original_width"] == 40
        assert mock_s3_service.upload_image.call_args.args[0].startswith("my-camera/")


class TestListPagination:
    def test_limit_is_capped(self, client: TestClient) -> None:
        assert client.get("/api/images", params={"limit": 500}).status_code == 200
        assert client.get("/api/images", params={"limit": 501}).status_code == 422
        assert client.get("/api/images", params={"offset": -1}).status_code == 422

    async def test_pages_are_disjoint_and_complete(self, client: TestClient, async_engine: AsyncEngine) -> None:
        async with AsyncSession(async_engine) as session:
            for index in range(7):
                session.add(Image(source_name="manual", storage_path=f"manual/{index}.jpg"))
            await session.commit()
        seen = [
            image["id"]
            for offset in range(0, 7, 3)
            for image in client.get("/api/images", params={"limit": 3, "offset": offset}).json()
        ]
        assert len(seen) == len(set(seen)) == 7

    async def test_source_url_prefix_is_literal(self, client: TestClient, async_engine: AsyncEngine) -> None:
        """``_`` and ``%`` in a prefix must not act as LIKE wildcards."""
        async with AsyncSession(async_engine) as session:
            session.add(Image(source_name="x", storage_path="x/1.jpg", source_url="https://a.test/my_album/1"))
            session.add(Image(source_name="x", storage_path="x/2.jpg", source_url="https://a.test/myXalbum/2"))
            await session.commit()
        hits = client.get("/api/images", params={"source_url_prefix": "https://a.test/my_album/"}).json()
        assert [h["source_url"] for h in hits] == ["https://a.test/my_album/1"]


async def _image_with_dependants(async_engine: AsyncEngine, seed_profile: DeviceProfile, **image_kwargs) -> Image:
    image = Image(source_name="manual", storage_path="manual/pic.jpg", **image_kwargs)
    grid = Grid(name="wall", width_cm=10, height_cm=10, current_image_id=image.id)
    device = Device(device_id="panel", device_profile_id=seed_profile.id, current_image_id=image.id)
    async with AsyncSession(async_engine) as session:
        session.add_all([image, grid, device, ImageBook(image_id=image.id, position=0, book_id=1, title="Dune")])
        await session.commit()
        await session.refresh(image)
    return image


class TestImageDeletion:
    async def test_delete_removes_books_derived_objects_and_references(
        self, client: TestClient, async_engine: AsyncEngine, seed_profile: DeviceProfile, mock_s3_service: MagicMock
    ) -> None:
        image = await _image_with_dependants(async_engine, seed_profile)
        mock_s3_service.list_keys.side_effect = lambda prefix: [f"{prefix}panel-abc.jpg"]

        assert client.delete(f"/api/images/{image.id}").status_code == 204

        deleted = {call.args[0] for call in mock_s3_service.delete_object.call_args_list}
        assert {
            "manual/pic.jpg",
            "thumbs/w480/manual/pic.jpg",
            "thumbs/eink/s05/manual/pic.jpg.png",
            "derived/1600x1200/manual/pic.jpg",
            "derived/1200x1600/manual/pic.jpg",
        } <= deleted
        assert any(key.startswith("grids/") and f"/{image.id}/" in key for key in deleted)
        async with AsyncSession(async_engine) as session:
            assert (await session.exec(select(ImageBook))).all() == []
            assert (await session.exec(select(Device))).one().current_image_id is None
            assert (await session.exec(select(Grid))).one().current_image_id is None

    async def test_group_delete_with_images_uses_the_same_cleanup(
        self, client: TestClient, async_engine: AsyncEngine, seed_profile: DeviceProfile, mock_s3_service: MagicMock
    ) -> None:
        group = ImageGroup(name="story")
        async with AsyncSession(async_engine) as session:
            session.add(group)
            await session.commit()
            await session.refresh(group)
        await _image_with_dependants(async_engine, seed_profile, group_id=group.id)

        response = client.delete(f"/api/image-groups/{group.id}", params={"delete_images": "true"})

        assert response.status_code == 204
        deleted = {call.args[0] for call in mock_s3_service.delete_object.call_args_list}
        assert "thumbs/w240/manual/pic.jpg" in deleted
        async with AsyncSession(async_engine) as session:
            assert (await session.exec(select(Image))).all() == []
            assert (await session.exec(select(ImageBook))).all() == []

    async def test_storage_failure_still_deletes_the_row(
        self, client: TestClient, async_engine: AsyncEngine, seed_profile: DeviceProfile, mock_s3_service: MagicMock
    ) -> None:
        from minio.error import S3Error  # noqa: PLC0415 — only this test needs it

        image = await _image_with_dependants(async_engine, seed_profile)
        mock_s3_service.delete_object.side_effect = S3Error(
            code="InternalError", message="down", resource="/", request_id="r", host_id="h", response=MagicMock()
        )
        assert client.delete(f"/api/images/{image.id}").status_code == 204
        async with AsyncSession(async_engine) as session:
            assert (await session.exec(select(Image).where(col(Image.id) == image.id))).first() is None


def test_unknown_image_delete_is_404(client: TestClient) -> None:
    assert client.delete(f"/api/images/{uuid4()}").status_code == 404
