"""Thin wrapper around the MinIO SDK for image storage."""

import io
import logging
from collections.abc import Iterator
from typing import Any

from minio import Minio

from inky_image_display_api.config import Settings

logger = logging.getLogger(__name__)

_STREAM_CHUNK = 32 * 1024


class S3Service:
    """Manages image objects in S3-compatible storage."""

    def __init__(self, settings: Settings) -> None:
        """Initialise the MinIO client from application settings.

        Args:
            settings: Application settings with S3 writer credentials.

        """
        self._client = Minio(
            settings.s3_endpoint,
            access_key=settings.s3_writer_access_key,
            secret_key=settings.s3_writer_secret_key,
            secure=settings.s3_secure,
            region=settings.s3_region or "",
        )
        self._bucket = settings.s3_bucket

    def ensure_bucket_exists(self) -> None:
        """Create the configured bucket if it does not already exist."""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            logger.info("Created S3 bucket: %s", self._bucket)

    def upload_image(self, storage_path: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Upload image bytes to S3.

        Args:
            storage_path: Object key inside the bucket.
            data: Raw image bytes.
            content_type: MIME type of the image.

        """
        self._client.put_object(
            self._bucket,
            storage_path,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info("Uploaded %s to bucket %s", storage_path, self._bucket)

    def delete_object(self, storage_path: str) -> None:
        """Remove an object from S3.

        Args:
            storage_path: Object key to delete.

        """
        self._client.remove_object(self._bucket, storage_path)
        logger.info("Deleted %s from bucket %s", storage_path, self._bucket)

    def stat_object(self, storage_path: str) -> Any:
        """Stat an object (raises ``minio.error.S3Error`` when missing).

        Used by the media proxy to turn missing objects into clean 404s
        and to obtain the ETag for conditional GETs.
        """
        return self._client.stat_object(self._bucket, storage_path)

    def get_object_bytes(self, storage_path: str) -> bytes:
        """Read a full object into memory (for thumbnail generation)."""
        response = self._client.get_object(self._bucket, storage_path)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def iter_object(self, storage_path: str) -> Iterator[bytes]:
        """Yield an object's bytes in chunks, releasing the connection at the end."""
        response = self._client.get_object(self._bucket, storage_path)
        try:
            yield from response.stream(_STREAM_CHUNK)
        finally:
            response.close()
            response.release_conn()
