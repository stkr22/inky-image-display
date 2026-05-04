"""Tests for the HTTP registration helper."""

import httpx
import pytest
from inky_image_display_controller.config import APIConfig
from inky_image_display_controller.registration import register
from inky_image_display_shared.schemas import (
    DeviceRegistration,
    DisplayInfo,
    RegistrationResponse,
)


@pytest.mark.asyncio
async def test_register_posts_payload_and_parses_response(monkeypatch):
    captured: dict[str, object] = {}

    response_body = RegistrationResponse(
        status="registered",
        s3_endpoint="s3.test.local:9000",
        s3_bucket="bucket",
        s3_access_key="ak",
        s3_secret_key="sk",
        s3_secure=False,
    ).model_dump_json()

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content"] = request.content
        return httpx.Response(200, content=response_body)

    transport = httpx.MockTransport(handler)

    # Patch httpx.AsyncClient so the helper uses our mock transport.
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("inky_image_display_controller.registration.httpx.AsyncClient", factory)

    payload = DeviceRegistration(
        device_id="test-device",
        display=DisplayInfo(width=1600, height=1200),
        room="Test Room",
    )
    result = await register(APIConfig(url="http://api.test"), payload)

    assert captured["url"] == "http://api.test/api/devices/register"
    assert captured["content"] == payload.model_dump_json().encode()
    assert result.status == "registered"
    assert result.s3_access_key == "ak"
