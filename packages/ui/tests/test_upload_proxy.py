"""Tests for the /internal/upload proxy route."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient


def test_upload_forwards_file_and_metadata_to_api(
    client: TestClient,
    route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
) -> None:
    captured: dict[str, bytes] = {}
    image_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(201, json={"id": str(image_id), "storage_path": "manual/x.jpg"})

    route_handlers[("POST", "/api/images")] = handler

    response = client.post(
        "/internal/upload",
        files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
        data={"metadata": json.dumps({"source_name": "manual", "title": "t"})},
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(image_id)
    # Upstream API received the forwarded multipart with metadata JSON
    body = captured["body"]
    assert b'name="metadata"' in body
    assert b'"title": "t"' in body or b'"title":"t"' in body


def test_upload_rejects_invalid_metadata_json(client: TestClient) -> None:
    response = client.post(
        "/internal/upload",
        files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
        data={"metadata": "not-json"},
    )
    assert response.status_code == 422


def test_upload_rejects_metadata_that_is_not_an_object(client: TestClient) -> None:
    response = client.post(
        "/internal/upload",
        files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
        data={"metadata": "[1, 2, 3]"},
    )
    assert response.status_code == 422


def test_upload_propagates_api_error(
    client: TestClient,
    route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
) -> None:
    route_handlers[("POST", "/api/images")] = lambda _r: httpx.Response(400, json={"detail": "bad file"})

    response = client.post(
        "/internal/upload",
        files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
        data={"metadata": json.dumps({"source_name": "manual"})},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "bad file"
