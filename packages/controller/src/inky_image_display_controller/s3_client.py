"""S3/MinIO client for fetching images from object storage."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Any

import urllib3
from minio import Minio
from PIL import Image

from inky_image_display_controller.exceptions import CommunicationError

logger = logging.getLogger(__name__)

# MinIO's default urllib3 PoolManager has no read timeout, which lets a stale
# pooled connection hang an image fetch indefinitely when the proxy or Garage
# silently half-closes the socket. Bound it explicitly.
_HTTP_TIMEOUT = urllib3.Timeout(connect=5.0, read=30.0)
_HTTP_RETRIES = urllib3.Retry(total=3, backoff_factor=0.5)


class S3ImageClient:
    """Client for fetching images from S3-compatible object storage.

    The MinIO SDK is synchronous, so operations are wrapped with
    run_in_executor to avoid blocking the async event loop.
    """

    def __init__(self, executor: ThreadPoolExecutor | None = None) -> None:
        """Initialize the S3 client.

        Args:
            executor: Optional thread pool executor for async operations.

        """
        self._client: Minio | None = None
        self._bucket: str | None = None
        self._executor = executor or ThreadPoolExecutor(max_workers=2)

    def configure(  # noqa: PLR0913
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        region: str | None = None,
    ) -> None:
        """Configure the S3 client with credentials.

        Typically called after receiving RegistrationResponse from MQTT.

        Args:
            endpoint: S3 server endpoint (host:port).
            access_key: S3 access key.
            secret_key: S3 secret key.
            bucket: Bucket name containing images.
            secure: Whether to use HTTPS.
            region: Optional S3 region. Falls back to the client library default when None.

        """
        kwargs: dict[str, Any] = {
            "access_key": access_key,
            "secret_key": secret_key,
            "secure": secure,
            "http_client": urllib3.PoolManager(
                timeout=_HTTP_TIMEOUT,
                retries=_HTTP_RETRIES,
                maxsize=4,
            ),
        }
        if region is not None:
            kwargs["region"] = region
        self._client = Minio(endpoint, **kwargs)
        self._bucket = bucket
        logger.info("S3 client configured for endpoint: %s, bucket: %s", endpoint, bucket)

    @property
    def is_configured(self) -> bool:
        """Check if the client has been configured with credentials."""
        return self._client is not None and self._bucket is not None

    async def fetch_image(self, object_path: str) -> Image.Image:
        """Fetch an image from S3 storage and return as PIL Image.

        Runs the synchronous MinIO SDK operation in a thread pool
        to avoid blocking the async event loop.

        Args:
            object_path: Path to the object in the S3 bucket.

        Returns:
            PIL Image object.

        Raises:
            CommunicationError: If the S3 client is not configured or fetch fails.

        """
        if not self.is_configured:
            raise CommunicationError("S3 client not configured. Await registration.")

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                self._executor,
                self._fetch_image_sync,
                object_path,
            )
        except Exception as e:
            logger.exception("Failed to fetch image from S3: %s", object_path)
            raise CommunicationError(f"Failed to fetch image: {e}") from e

    def _fetch_image_sync(self, object_path: str) -> Image.Image:
        """Fetch image data from S3 synchronously.

        Args:
            object_path: Path to the object in the S3 bucket.

        Returns:
            PIL Image object.

        """
        assert self._client is not None
        assert self._bucket is not None

        logger.debug("Fetching image from S3: %s/%s", self._bucket, object_path)
        response = self._client.get_object(self._bucket, object_path)
        try:
            image_data = BytesIO(response.read())
            image = Image.open(image_data)
            # Load the image data into memory so we can close the response
            image.load()
            logger.debug("Successfully fetched image: %s (size: %s)", object_path, image.size)
            return image
        finally:
            response.close()
            response.release_conn()

    def close(self) -> None:
        """Clean up resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
