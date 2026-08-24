"""Tests for POST /api/images/process."""

from __future__ import annotations

import asyncio
import threading
from io import BytesIO
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from PIL import Image as PILImage

if TYPE_CHECKING:
    from fastapi import FastAPI


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


def test_concurrent_decodes_are_bounded(test_app: FastAPI, monkeypatch) -> None:
    """Each in-flight decode holds a display-sized raster, so the number of
    them running at once is a memory ceiling. Unbounded, FastAPI's 40-slot
    threadpool let the sync workers' parallel jobs stack 40 rasters and
    OOM-kill the API at 1Gi.
    """
    test_app.state.process_gate = asyncio.Semaphore(1)

    lock = threading.Lock()
    live = 0
    peak = 0

    def slow_process(*_args: object, **_kwargs: object) -> bytes:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        # Long enough that unbounded requests would demonstrably overlap.
        threading.Event().wait(0.15)
        with lock:
            live -= 1
        return b"jpeg"

    monkeypatch.setattr(
        "inky_image_display_api.routes.images_process.ImageProcessor.process_for_display",
        slow_process,
    )

    src = _make_jpeg(64, 64)

    def post(client: TestClient) -> int:
        return client.post(
            "/api/images/process",
            files={"file": ("source.jpg", src, "image/jpeg")},
            data={"width": "32", "height": "32"},
        ).status_code

    with TestClient(test_app) as client:
        threads = [threading.Thread(target=lambda: post(client)) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert peak == 1, f"gate allowed {peak} concurrent decodes, expected 1"
