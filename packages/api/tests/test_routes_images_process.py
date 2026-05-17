"""Tests for POST /api/images/process."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image as PILImage

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def _make_jpeg(width: int, height: int, color: tuple[int, int, int] = (40, 120, 200)) -> bytes:
    """Encode a solid-colour JPEG of the requested size."""
    img = PILImage.new("RGB", (width, height), color=color)
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_process_returns_resized_jpeg(client: TestClient) -> None:
    """Happy path: a large source is resized to the requested dimensions."""
    src = _make_jpeg(4000, 3000)
    response = client.post(
        "/api/images/process",
        files={"file": ("source.jpg", src, "image/jpeg")},
        data={"width": "1600", "height": "1200"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    out = PILImage.open(BytesIO(response.content))
    assert out.size == (1600, 1200)


def test_undersized_returns_422(client: TestClient) -> None:
    """A source smaller than the target must produce HTTP 422."""
    src = _make_jpeg(800, 600)
    response = client.post(
        "/api/images/process",
        files={"file": ("source.jpg", src, "image/jpeg")},
        data={"width": "1600", "height": "1200"},
    )
    assert response.status_code == 422
    # FastAPI wraps the detail under the standard error envelope.
    body = response.json()
    assert "too small" in body["detail"].lower()


def test_upscale_flag_allows_small_source(client: TestClient) -> None:
    """With upscale=true the same undersized source must succeed."""
    src = _make_jpeg(800, 600)
    response = client.post(
        "/api/images/process",
        files={"file": ("source.jpg", src, "image/jpeg")},
        data={"width": "1600", "height": "1200", "upscale": "true"},
    )
    assert response.status_code == 200
    out = PILImage.open(BytesIO(response.content))
    assert out.size == (1600, 1200)


def test_missing_form_fields_returns_validation_error(client: TestClient) -> None:
    """Missing required form fields produce FastAPI's 422 validation error."""
    src = _make_jpeg(2000, 1500)
    response = client.post(
        "/api/images/process",
        files={"file": ("source.jpg", src, "image/jpeg")},
        # width/height missing
    )
    assert response.status_code == 422
