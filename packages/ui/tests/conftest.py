"""Shared test fixtures for the UI package."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_ui.api_client import ApiClient
from inky_image_display_ui.s3_proxy import router as media_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator


@pytest.fixture
def route_handlers() -> dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]]:
    """Mutable registry mapping (METHOD, path) tuples to response callables.

    Tests populate this dict to stub API responses.
    """
    return {}


@pytest.fixture
def api_transport(
    route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
) -> httpx.MockTransport:
    """Build an :class:`httpx.MockTransport` backed by ``route_handlers``."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        fn = route_handlers.get(key)
        if fn is None:
            return httpx.Response(404, json={"detail": f"No handler for {key}"})
        return fn(request)

    return httpx.MockTransport(handler)


@pytest.fixture
async def api_client(api_transport: httpx.MockTransport) -> AsyncIterator[ApiClient]:
    """Yield an :class:`ApiClient` wired to the mock transport."""
    async with httpx.AsyncClient(transport=api_transport, base_url="http://api.test") as client:
        yield ApiClient(client)


@pytest.fixture
def fake_minio_stat() -> MagicMock:
    """Return a fake minio ``stat_object`` result with sensible defaults."""
    stat = MagicMock()
    stat.etag = "deadbeef"
    stat.content_type = "image/jpeg"
    return stat


@pytest.fixture
def fake_minio(fake_minio_stat: MagicMock) -> MagicMock:
    """Return a fake ``Minio`` client pre-wired to return ``fake_minio_stat``."""
    client = MagicMock()
    client.stat_object = MagicMock(return_value=fake_minio_stat)
    http_response = MagicMock()
    http_response.stream = MagicMock(return_value=iter([b"test-image-bytes"]))
    http_response.close = MagicMock()
    http_response.release_conn = MagicMock()
    client.get_object = MagicMock(return_value=http_response)
    return client


@pytest.fixture
def fake_settings() -> MagicMock:
    """Minimal settings stub with the fields the proxies read."""
    settings = MagicMock()
    settings.s3_bucket = "test-bucket"
    settings.media_cache_max_age = 3600
    return settings


@pytest.fixture
def test_app(
    api_client: ApiClient,
    fake_minio: MagicMock,
    fake_settings: MagicMock,
) -> FastAPI:
    """Build a FastAPI app matching ``main.build_app`` but with injected deps."""
    app = FastAPI()
    app.state.api_client = api_client
    app.state.minio_client = fake_minio
    app.state.settings = fake_settings

    @app.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(media_router)
    return app


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """Synchronous test client over the assembled app."""
    with TestClient(test_app) as c:
        yield c
