"""S3-compatible object storage shared by every sync source.

Immich, Gemini, Calibre and display jobs all upload their finished JPEGs the
same way, so the writer config and client live here rather than under any one
source.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import TYPE_CHECKING

import urllib3
from minio import Minio
from minio.error import S3Error
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    import logging

# MinIO's default urllib3 PoolManager has no usable read timeout, so a stale
# pooled connection that the proxy or Garage silently half-closed would hang
# the worker's whole cycle. Same bound the controller uses for its reads.
HTTP_TIMEOUT = urllib3.Timeout(connect=5.0, read=30.0)
HTTP_RETRIES = urllib3.Retry(total=3, backoff_factor=0.5)


class S3WriterConfig(BaseSettings):
    """S3-compatible storage configuration with write access for sync operations.

    Separate from the read-only credentials handed to controllers, so only
    the sync service holds write access.

    Environment variables:
        S3_WRITER_ENDPOINT: S3 server endpoint
        S3_WRITER_BUCKET: Target bucket (default: inky-images)
        S3_WRITER_SECURE: Use HTTPS (default: False)
        S3_WRITER_ACCESS_KEY: Access key with write permissions
        S3_WRITER_SECRET_KEY: Secret key with write permissions
        S3_WRITER_REGION: S3 region (default: minio-py built-in)
    """

    model_config = SettingsConfigDict(env_prefix="S3_WRITER_")

    endpoint: str = Field(description="S3 server endpoint")
    bucket: str = Field(default="inky-images", description="Bucket for image storage")
    secure: bool = Field(default=False, description="Use HTTPS for S3 connection")
    access_key: str = Field(description="Access key with write permissions")
    # SecretStr keeps the key out of reprs and accidental log lines.
    secret_key: SecretStr = Field(description="Secret key with write permissions")
    region: str | None = Field(default=None, description="S3 region (defaults to minio-py built-in)")


class S3StorageClient:
    """Async facade over the synchronous minio-py client.

    Every call is pushed to a worker thread: the sync worker runs all job
    families on one event loop, and a blocking upload would stall the MQTT
    keepalive and every other in-flight request with it.
    """

    def __init__(self, config: S3WriterConfig, logger: logging.Logger) -> None:
        """Build the MinIO client with bounded timeouts."""
        self.config = config
        self.logger = logger
        self._client = Minio(
            endpoint=config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key.get_secret_value(),
            secure=config.secure,
            region=config.region if config.region is not None else "",
            http_client=urllib3.PoolManager(timeout=HTTP_TIMEOUT, retries=HTTP_RETRIES, maxsize=4),
        )

    async def ensure_bucket_exists(self) -> None:
        """Create the bucket if it doesn't exist."""
        if not await asyncio.to_thread(self._client.bucket_exists, self.config.bucket):
            await asyncio.to_thread(self._client.make_bucket, self.config.bucket)
            self.logger.info("Created bucket: %s", self.config.bucket)

    async def object_exists(self, object_path: str) -> bool:
        """Report whether an object already exists in the bucket."""
        try:
            await asyncio.to_thread(self._client.stat_object, self.config.bucket, object_path)
        except S3Error:
            return False
        return True

    async def upload_from_bytes(self, object_path: str, data: bytes, content_type: str) -> str:
        """Upload ``data`` to ``object_path`` and return the path."""
        await asyncio.to_thread(
            self._client.put_object,
            bucket_name=self.config.bucket,
            object_name=object_path,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        self.logger.debug("Uploaded %s (%d bytes)", object_path, len(data))
        return object_path
