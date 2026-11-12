"""Tests for the controller's S3 image client."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest
from inky_image_display_controller import s3_client as s3_module
from inky_image_display_controller.exceptions import CommunicationError
from inky_image_display_controller.s3_client import S3ImageClient
from PIL import Image


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 6), "blue").save(buf, format="JPEG")
    return buf.getvalue()


def test_configure_builds_minio_with_bounded_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    minio = MagicMock()
    monkeypatch.setattr(s3_module, "Minio", minio)
    client = S3ImageClient()
    try:
        client.configure(endpoint="s3.test:9000", access_key="ak", secret_key="sk", bucket="b", region="garage")
    finally:
        client.close()

    assert client.is_configured
    args, kwargs = minio.call_args
    assert args == ("s3.test:9000",)
    assert kwargs["region"] == "garage"
    # Without an explicit read timeout a half-closed pooled socket hangs the fetch forever.
    pool = kwargs["http_client"]
    assert pool.connection_pool_kw["timeout"].read_timeout == 30.0
    assert pool.connection_pool_kw["timeout"].connect_timeout == 5.0


@pytest.mark.asyncio
async def test_fetch_image_runs_in_executor_and_releases_response() -> None:
    client = S3ImageClient()
    response = MagicMock()
    response.read.return_value = _jpeg_bytes()
    client._client = MagicMock(get_object=MagicMock(return_value=response))
    client._bucket = "b"
    try:
        image = await client.fetch_image("gemini/x.jpg")
    finally:
        client.close()

    assert image.size == (8, 6)
    client._client.get_object.assert_called_once_with("b", "gemini/x.jpg")
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_image_wraps_errors() -> None:
    client = S3ImageClient()
    client._client = MagicMock(get_object=MagicMock(side_effect=OSError("reset")))
    client._bucket = "b"
    try:
        with pytest.raises(CommunicationError, match="reset"):
            await client.fetch_image("x.jpg")
    finally:
        client.close()


@pytest.mark.asyncio
async def test_fetch_image_requires_configuration() -> None:
    client = S3ImageClient()
    with pytest.raises(CommunicationError, match="not configured"):
        await client.fetch_image("x.jpg")
    client.close()
