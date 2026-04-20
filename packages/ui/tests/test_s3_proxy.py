"""Tests for the S3 proxy route."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from minio.error import S3Error

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_media_returns_bytes_with_content_type(client: TestClient, fake_minio: MagicMock) -> None:
    response = client.get("/media/manual/test.jpg")

    assert response.status_code == 200
    assert response.content == b"test-image-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert "public, max-age=3600" in response.headers["cache-control"]
    assert response.headers["etag"] == "deadbeef"
    fake_minio.stat_object.assert_called_once_with("test-bucket", "manual/test.jpg")
    fake_minio.get_object.assert_called_once_with("test-bucket", "manual/test.jpg")


def test_media_returns_304_on_matching_etag(client: TestClient) -> None:
    response = client.get("/media/manual/test.jpg", headers={"If-None-Match": "deadbeef"})
    assert response.status_code == 304


def test_media_returns_404_for_missing_object(client: TestClient, fake_minio: MagicMock) -> None:
    exc = S3Error(
        code="NoSuchKey",
        message="missing",
        resource="/test-bucket/missing.jpg",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )
    fake_minio.stat_object.side_effect = exc

    response = client.get("/media/missing.jpg")
    assert response.status_code == 404


def test_media_returns_502_for_other_s3_errors(client: TestClient, fake_minio: MagicMock) -> None:
    exc = S3Error(
        code="AccessDenied",
        message="nope",
        resource="/test-bucket/x.jpg",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )
    fake_minio.stat_object.side_effect = exc

    response = client.get("/media/x.jpg")
    assert response.status_code == 502


def test_media_object_key_with_slashes_routes_correctly(client: TestClient, fake_minio: MagicMock) -> None:
    response = client.get("/media/manual/sub/folder/pic.jpg")
    assert response.status_code == 200
    fake_minio.stat_object.assert_called_once_with("test-bucket", "manual/sub/folder/pic.jpg")


def test_media_falls_back_to_image_jpeg_when_content_type_absent(
    client: TestClient, fake_minio_stat: MagicMock
) -> None:
    fake_minio_stat.content_type = None
    response = client.get("/media/any.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
