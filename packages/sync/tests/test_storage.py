"""Tests for the shared S3 writer used by every sync source."""

import logging
from unittest.mock import MagicMock

from inky_image_display_sync.storage import HTTP_TIMEOUT, S3StorageClient, S3WriterConfig
from minio.error import S3Error


def _client() -> S3StorageClient:
    config = S3WriterConfig(endpoint="localhost:9000", access_key="k", secret_key="s3-secret")
    return S3StorageClient(config=config, logger=logging.getLogger("test"))


def test_minio_is_built_with_a_bounded_read_timeout():
    # minio's own PoolManager has no read timeout; a half-closed pooled
    # socket would otherwise hang the worker's whole cycle.
    pool = _client()._client._http
    assert pool.connection_pool_kw["timeout"] is HTTP_TIMEOUT
    assert HTTP_TIMEOUT.read_timeout is not None


def test_secret_key_is_masked_in_config_repr():
    config = S3WriterConfig(endpoint="localhost:9000", access_key="k", secret_key="s3-secret")
    assert "s3-secret" not in repr(config)


async def test_calls_run_through_the_async_facade():
    client = _client()
    minio = MagicMock()
    minio.bucket_exists.return_value = False
    minio.stat_object.side_effect = S3Error(MagicMock(), "NoSuchKey", "missing", "r", "req", "host")
    client._client = minio

    await client.ensure_bucket_exists()
    assert await client.object_exists("a.jpg") is False
    assert await client.upload_from_bytes("a.jpg", b"jpeg", "image/jpeg") == "a.jpg"

    minio.make_bucket.assert_called_once_with("inky-images")
    assert minio.put_object.call_args.kwargs["length"] == 4
