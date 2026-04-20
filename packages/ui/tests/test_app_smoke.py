"""Smoke tests covering FastAPI assembly and route ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from inky_image_display_ui import formatting
from minio.error import S3Error

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_media_missing_object_returns_404_from_media_router(client: TestClient, fake_minio: MagicMock) -> None:
    """``/media/...`` must be served by the media router rather than falling through."""
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
    # The response should be JSON from FastAPI's HTTPException, not HTML from Flet
    assert response.headers["content-type"].startswith("application/json")


def test_formatting_module_imports() -> None:
    """Cheap import smoke test for the formatting helpers module."""
    assert formatting.format_datetime(None) == "—"
    assert formatting.format_tags(None) == []
    assert formatting.format_tags("a, b , c ") == ["a", "b", "c"]
    assert formatting.join_tags(["a", " b "]) == "a, b"
    assert formatting.join_tags([]) is None
