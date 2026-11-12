"""Tests for the DisplayAPIClient: auth header, image counting and paging."""

import logging
from uuid import uuid4

import httpx2
import pytest
from inky_image_display_sync.api_client import IMAGE_PAGE_SIZE, DisplayAPIClient, DisplayAPIError
from inky_image_display_sync.immich.client import ImmichClient
from inky_image_display_sync.immich.config import APIClientConfig, ImmichConnectionConfig
from pydantic import HttpUrl, SecretStr


def test_token_is_sent_as_x_api_key_header():
    config = APIClientConfig(base_url=HttpUrl("http://api.test"), token=SecretStr("sync-key"))
    client = DisplayAPIClient(config=config, logger=logging.getLogger(__name__))
    assert client._client.headers["x-api-key"] == "sync-key"


def test_no_token_sends_no_header():
    config = APIClientConfig(base_url=HttpUrl("http://api.test"))
    client = DisplayAPIClient(config=config, logger=logging.getLogger(__name__))
    assert "x-api-key" not in client._client.headers


def _client_with(handler) -> tuple[DisplayAPIClient, list[httpx2.Request]]:
    """A client whose HTTP layer is an in-process fake API."""
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    client = DisplayAPIClient(config=APIClientConfig(base_url=HttpUrl("http://api.test")), logger=logging.getLogger())
    client._client = httpx2.AsyncClient(base_url="http://api.test", transport=httpx2.MockTransport(record))
    return client, seen


def _image(n: int) -> dict:
    return {
        "id": str(uuid4()),
        "source_name": "immich",
        "source_id": f"a{n}",
        "sync_job_name": "job",
        "storage_path": f"immich/a{n}.jpg",
        "source_url": None,
        "title": None,
        "description": None,
        "author": None,
        "original_width": 800,
        "original_height": 480,
        "is_portrait": False,
        "display_duration_seconds": None,
        "priority": 0,
        "last_displayed_at": None,
        "expires_at": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "tags": None,
    }


async def test_count_reads_the_total_header_from_a_one_row_page():
    client, seen = _client_with(lambda _req: httpx2.Response(200, json=[_image(0)], headers={"X-Total-Count": "2500"}))

    assert await client.count_images(source_name="immich", sync_job_name="job") == 2500
    assert seen[0].url.params["limit"] == "1"
    assert seen[0].url.params["sync_job_name"] == "job"


async def test_count_without_total_header_is_an_error():
    client, _ = _client_with(lambda _req: httpx2.Response(200, json=[]))

    with pytest.raises(DisplayAPIError):
        await client.count_images()


async def test_list_all_pages_past_the_page_size_and_server_caps():
    # 1200 rows; the server caps pages at 300, below what we ask for, so the
    # loop has to follow the total rather than a short page.
    rows = [_image(n) for n in range(1200)]

    def handler(request: httpx2.Request) -> httpx2.Response:
        offset = int(request.url.params["offset"])
        limit = min(int(request.url.params["limit"]), 300)
        return httpx2.Response(200, json=rows[offset : offset + limit], headers={"X-Total-Count": str(len(rows))})

    client, seen = _client_with(handler)

    images = await client.list_all_images(source_name="immich")

    assert [i.source_id for i in images] == [f"a{n}" for n in range(1200)]
    assert all(int(r.url.params["limit"]) <= IMAGE_PAGE_SIZE for r in seen)
    assert len(seen) == 4


def test_immich_api_key_is_secret_but_sent_in_clear():
    config = ImmichConnectionConfig(base_url=HttpUrl("http://immich.test"), api_key=SecretStr("immich-key"))
    assert "immich-key" not in repr(config)
    client = ImmichClient(config=config, logger=logging.getLogger())
    assert client.api_key.get_secret_value() == "immich-key"
