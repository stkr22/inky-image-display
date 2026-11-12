"""Thin wrapper around the MinIO SDK for image storage."""

import io
import logging
from collections.abc import Iterator
from typing import Any

from minio import Minio
from minio.error import S3Error

from inky_image_display_api.config import Settings

logger = logging.getLogger(__name__)

_STREAM_CHUNK = 32 * 1024
_MISSING_CODES = frozenset({"NoSuchKey", "NoSuchObject"})


def stat_or_none(s3: "S3Service", key: str) -> Any:
    """Stat ``key``; ``None`` only when the object genuinely does not exist.

    Every derived-object cache (thumbnails, previews, panel crops) asks
    "is it there?" before rendering. Treating *any* error as a miss turns
    an S3 outage into a burst of full-size decodes that can't even be
    uploaded, so only a not-found answer counts as a miss and anything
    else propagates as ``S3Error``.
    """
    try:
        return s3.stat_object(key)
    except S3Error as exc:
        if exc.code in _MISSING_CODES:
            return None
        raise


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

    def list_keys(self, prefix: str) -> list[str]:
        """Return every object key under ``prefix`` (recursive)."""
        return [
            obj.object_name
            for obj in self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
            if obj.object_name is not None
        ]

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
