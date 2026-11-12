"""Tests for how the Gemini helpers build, use and close their SDK client.

The pinned API version and the timeout are the whole point of the shared
factory, so they are asserted against a real ``genai.Client`` rather than a
mock; the request path itself is faked at the ``genai.Client`` seam.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from inky_image_display_shared.ai import (
    GeminiGenerationError,
    RenderedPrompt,
    ShelfReading,
    SpineReading,
    generate_image_bytes,
    transcribe_spines,
)
from inky_image_display_shared.ai._client import DEFAULT_TIMEOUT_S, GEMINI_API_VERSION, build_client

_PATCH_TARGET = "inky_image_display_shared.ai._client.genai.Client"


def _prompt() -> RenderedPrompt:
    return RenderedPrompt(
        style="S", palette="P", legibility="L", composition="C {subject}", background="B", is_portrait=False
    )


def _fake_client(response: object) -> MagicMock:
    """A genai.Client stand-in whose ``.aio`` works as an async context manager."""
    client = MagicMock()
    aio = client.aio
    aio.__aenter__ = AsyncMock(return_value=aio)
    aio.__aexit__ = AsyncMock(return_value=None)
    aio.models.generate_content = AsyncMock(return_value=response)
    # The sync path must not be used: it blocks a worker thread uncancellably.
    client.models.generate_content.side_effect = AssertionError("sync client used")
    return client


def _image_response(data: bytes | None) -> SimpleNamespace:
    part = SimpleNamespace(inline_data=SimpleNamespace(data=data) if data is not None else None)
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")])


def test_build_client_pins_api_version_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # The explicit http_options must win over the SDK's env-based default.
    monkeypatch.setenv("GOOGLE_GENAI_API_VERSION", "v1")
    client = build_client("key")
    try:
        options: Any = client._api_client._http_options
        assert options.api_version == GEMINI_API_VERSION == "v1beta"
        assert options.timeout == int(DEFAULT_TIMEOUT_S * 1000)
    finally:
        client.close()


def test_build_client_timeout_is_configurable() -> None:
    client = build_client("key", timeout_s=7.5)
    try:
        options: Any = client._api_client._http_options
        assert options.timeout == 7500
    finally:
        client.close()


@pytest.mark.asyncio
async def test_generate_image_uses_async_client_and_closes_it() -> None:
    fake = _fake_client(_image_response(b"png-bytes"))
    with patch(_PATCH_TARGET, return_value=fake) as client_cls:
        result = await generate_image_bytes("key", _prompt(), "a fox", model="m", reference_image=b"ref")

    assert result == b"png-bytes"
    http_options = client_cls.call_args.kwargs["http_options"]
    assert http_options.api_version == "v1beta"
    assert http_options.timeout == int(DEFAULT_TIMEOUT_S * 1000)
    call = fake.aio.models.generate_content.await_args
    assert call.kwargs["model"] == "m"
    assert call.kwargs["config"].response_modalities == ["IMAGE"]
    assert call.kwargs["config"].image_config.aspect_ratio == "4:3"
    assert len(call.kwargs["contents"]) == 2  # reference image first, then prompt
    fake.aio.__aexit__.assert_awaited_once()
    fake.close.assert_called_once()


@pytest.mark.asyncio
async def test_generate_image_without_parts_raises_and_still_closes() -> None:
    fake = _fake_client(SimpleNamespace(candidates=[SimpleNamespace(content=None, finish_reason="SAFETY")]))
    with patch(_PATCH_TARGET, return_value=fake), pytest.raises(GeminiGenerationError, match="SAFETY"):
        await generate_image_bytes("key", _prompt(), "a fox")
    fake.close.assert_called_once()


@pytest.mark.asyncio
async def test_generate_image_without_inline_data_raises() -> None:
    fake = _fake_client(_image_response(None))
    with patch(_PATCH_TARGET, return_value=fake), pytest.raises(GeminiGenerationError, match="no inline image"):
        await generate_image_bytes("key", _prompt(), "a fox")


@pytest.mark.asyncio
async def test_sdk_error_propagates_and_client_is_closed() -> None:
    fake = _fake_client(None)
    fake.aio.models.generate_content.side_effect = RuntimeError("503")
    with patch(_PATCH_TARGET, return_value=fake), pytest.raises(RuntimeError, match="503"):
        await generate_image_bytes("key", _prompt(), "a fox")
    fake.aio.__aexit__.assert_awaited_once()
    fake.close.assert_called_once()


@pytest.mark.asyncio
async def test_transcribe_spines_parses_and_closes() -> None:
    reading = ShelfReading(spines=[SpineReading(title="T", author="A")])
    fake = _fake_client(SimpleNamespace(parsed=reading, text=None))
    with patch(_PATCH_TARGET, return_value=fake):
        spines = await transcribe_spines("key", b"jpeg")

    assert spines == reading.spines
    fake.close.assert_called_once()


@pytest.mark.asyncio
async def test_transcribe_spines_unreadable_raises() -> None:
    fake = _fake_client(SimpleNamespace(parsed=None, text="nope"))
    with patch(_PATCH_TARGET, return_value=fake), pytest.raises(GeminiGenerationError, match="unreadable"):
        await transcribe_spines("key", b"jpeg")
