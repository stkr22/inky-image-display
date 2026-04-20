"""Tests for the async API client."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import httpx
import pytest
from inky_image_display_ui.api_client import ApiClient, ApiError, DeviceNotConnectedError

if TYPE_CHECKING:
    from collections.abc import Callable


def _json(status: int, body: object) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status, json=body)


class TestListImages:
    async def test_sends_filters_and_pagination(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        captured: dict[str, httpx.URL] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = request.url
            return httpx.Response(200, json=[])

        route_handlers[("GET", "/api/images")] = handler
        await api_client.list_images(source_name="manual", is_portrait=True, limit=20, offset=40)

        query = dict(captured["url"].params)
        assert query["source_name"] == "manual"
        assert query["is_portrait"] == "true"
        assert query["limit"] == "20"
        assert query["offset"] == "40"

    async def test_omits_none_filters(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        captured: dict[str, httpx.URL] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = request.url
            return httpx.Response(200, json=[])

        route_handlers[("GET", "/api/images")] = handler
        await api_client.list_images()

        query = dict(captured["url"].params)
        assert "source_name" not in query
        assert "is_portrait" not in query
        assert query["limit"] == "100"
        assert query["offset"] == "0"


class TestGetImage:
    async def test_returns_dict(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        route_handlers[("GET", f"/api/images/{image_id}")] = _json(200, {"id": str(image_id), "title": "x"})
        result = await api_client.get_image(image_id)
        assert result["title"] == "x"


class TestUploadImage:
    async def test_sends_multipart_with_metadata_json_string(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        captured: dict[str, bytes] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            captured["content_type"] = request.headers["content-type"].encode()
            return httpx.Response(201, json={"id": str(uuid4()), "storage_path": "manual/x.jpg"})

        route_handlers[("POST", "/api/images")] = handler
        await api_client.upload_image(b"\xff\xd8\xff", "x.jpg", {"source_name": "manual", "title": "t"})

        assert captured["content_type"].startswith(b"multipart/form-data")
        body = captured["body"]
        # Form field with metadata JSON must be present
        assert b'name="metadata"' in body
        assert b'"source_name": "manual"' in body or b'"source_name":"manual"' in body
        # Title also present in the JSON blob
        assert b'"title": "t"' in body or b'"title":"t"' in body
        # File field with the raw bytes
        assert b'name="file"' in body
        assert b"\xff\xd8\xff" in body


class TestUpdateImage:
    async def test_converts_uuids_and_datetimes(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"id": str(image_id)})

        route_handlers[("PUT", f"/api/images/{image_id}")] = handler
        await api_client.update_image(image_id, {"title": "new", "priority": 7})

        assert captured["json"] == {"title": "new", "priority": 7}


class TestDeleteImage:
    async def test_returns_none_on_204(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        route_handlers[("DELETE", f"/api/images/{image_id}")] = lambda _r: httpx.Response(204)
        assert await api_client.delete_image(image_id) is None

    async def test_raises_on_error(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        route_handlers[("DELETE", f"/api/images/{image_id}")] = _json(500, {"detail": "boom"})
        with pytest.raises(ApiError) as excinfo:
            await api_client.delete_image(image_id)
        assert excinfo.value.status_code == 500
        assert excinfo.value.detail == "boom"


class TestDevices:
    async def test_list_devices_forwards_filters(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        captured: dict[str, httpx.URL] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = request.url
            return httpx.Response(200, json=[])

        route_handlers[("GET", "/api/devices")] = handler
        await api_client.list_devices(room="Kitchen", is_online=True)

        params = dict(captured["url"].params)
        assert params["room"] == "Kitchen"
        assert params["is_online"] == "true"

    async def test_display_image_sends_uuid_as_string(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "ok"})

        route_handlers[("POST", "/api/devices/test-display/display")] = handler
        await api_client.display_image("test-display", image_id)
        assert captured["json"] == {"image_id": str(image_id)}

    async def test_display_image_maps_404_to_device_not_connected(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        route_handlers[("POST", "/api/devices/test-display/display")] = _json(404, {"detail": "Device not connected"})
        with pytest.raises(DeviceNotConnectedError):
            await api_client.display_image("test-display", image_id)

    async def test_display_image_other_404_is_plain_api_error(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = uuid4()
        route_handlers[("POST", "/api/devices/test-display/display")] = _json(404, {"detail": "Image not found"})
        with pytest.raises(ApiError) as excinfo:
            await api_client.display_image("test-display", image_id)
        assert not isinstance(excinfo.value, DeviceNotConnectedError)
        assert excinfo.value.detail == "Image not found"

    async def test_next_image_maps_404_to_device_not_connected(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        route_handlers[("POST", "/api/devices/test-display/next")] = _json(404, {"detail": "Device not connected"})
        with pytest.raises(DeviceNotConnectedError):
            await api_client.next_image("test-display")

    async def test_clear_device_maps_404_to_device_not_connected(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        route_handlers[("POST", "/api/devices/test-display/clear")] = _json(404, {"detail": "Device not connected"})
        with pytest.raises(DeviceNotConnectedError):
            await api_client.clear_device("test-display")


class TestSyncJobs:
    async def test_list_sync_jobs_filter(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        captured: dict[str, httpx.URL] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = request.url
            return httpx.Response(200, json=[])

        route_handlers[("GET", "/api/sync-jobs")] = handler
        await api_client.list_sync_jobs(is_active=True)
        assert dict(captured["url"].params)["is_active"] == "true"

    async def test_create_sync_job_sends_json(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        captured: dict[str, object] = {}
        target = uuid4()

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(201, json={"id": str(uuid4())})

        route_handlers[("POST", "/api/sync-jobs")] = handler
        await api_client.create_sync_job(
            {"name": "test", "target_device_id": target, "strategy": "RANDOM", "count": 10}
        )
        assert captured["json"] == {
            "name": "test",
            "target_device_id": str(target),
            "strategy": "RANDOM",
            "count": 10,
        }

    async def test_delete_sync_job(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        job_id = uuid4()
        route_handlers[("DELETE", f"/api/sync-jobs/{job_id}")] = lambda _r: httpx.Response(204)
        assert await api_client.delete_sync_job(job_id) is None


class TestApiErrorParsing:
    async def test_non_json_body_uses_text(
        self,
        api_client: ApiClient,
        route_handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]],
    ) -> None:
        image_id = UUID("12345678-1234-5678-1234-567812345678")
        route_handlers[("GET", f"/api/images/{image_id}")] = lambda _r: httpx.Response(500, text="upstream died")
        with pytest.raises(ApiError) as excinfo:
            await api_client.get_image(image_id)
        assert excinfo.value.detail == "upstream died"
