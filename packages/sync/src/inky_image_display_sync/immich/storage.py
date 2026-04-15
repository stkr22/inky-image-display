"""S3-compatible storage utilities for Immich sync."""

import logging
from collections.abc import AsyncIterator
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from inky_image_display_sync.immich.config import S3WriterConfig


class S3StorageClient:
    """S3-compatible storage client for uploading images.

    Wraps the synchronous minio-py library.
    AIDEV-NOTE: minio-py is synchronous; consider running in executor for large uploads.
    """

    def __init__(
        self,
        config: S3WriterConfig,
        logger: logging.Logger,
    ) -> None:
        """Initialize S3 client.

        Args:
            config: S3 configuration with write credentials
            logger: Logger instance

        """
        self.config = config
        self.logger = logger
        self._client = Minio(
            endpoint=config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
            region=config.region if config.region is not None else "",
        )

    def ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist."""
        if not self._client.bucket_exists(self.config.bucket):
            self._client.make_bucket(self.config.bucket)
            self.logger.info("Created bucket: %s", self.config.bucket)

    def object_exists(self, object_path: str) -> bool:
        """Check if an object already exists in S3.

        Args:
            object_path: Full path within bucket

        Returns:
            True if object exists

        """
        try:
            self._client.stat_object(self.config.bucket, object_path)
            return True
        except S3Error:
            return False

    async def upload_from_stream(
        self,
        object_path: str,
        data_stream: AsyncIterator[bytes],
        content_type: str,
    ) -> str:
        """Upload file from async byte stream.

        Collects stream into memory then uploads.
        AIDEV-NOTE: For very large files, consider chunked upload or temp file.

        Args:
            object_path: Destination path in bucket
            data_stream: Async iterator of bytes
            content_type: MIME type

        Returns:
            Full storage path (bucket/object_path)

        """
        # Collect stream into buffer
        buffer = BytesIO()
        async for chunk in data_stream:
            buffer.write(chunk)

        buffer.seek(0)
        size = buffer.getbuffer().nbytes

        self._client.put_object(
            bucket_name=self.config.bucket,
            object_name=object_path,
            data=buffer,
            length=size,
            content_type=content_type,
        )

        self.logger.debug("Uploaded %s (%d bytes)", object_path, size)
        return object_path

    def delete_object(self, object_path: str) -> None:
        """Delete an object from S3.

        Args:
            object_path: Full path within bucket

        Raises:
            S3Error: If deletion fails

        """
        self._client.remove_object(self.config.bucket, object_path)
        self.logger.debug("Deleted %s", object_path)

    def upload_from_bytes(
        self,
        object_path: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """Upload file from bytes.

        Args:
            object_path: Destination path in bucket
            data: File content as bytes
            content_type: MIME type

        Returns:
            Full storage path (bucket/object_path)

        """
        buffer = BytesIO(data)
        size = len(data)

        self._client.put_object(
            bucket_name=self.config.bucket,
            object_name=object_path,
            data=buffer,
            length=size,
            content_type=content_type,
        )

        self.logger.debug("Uploaded %s (%d bytes)", object_path, size)
        return object_path
