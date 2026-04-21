"""HTTP client for the Inky Image Display REST API."""

import logging
from datetime import datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

from inky_image_display_sync.immich.config import APIClientConfig

# ---------------------------------------------------------------------------
# Local response / payload models (mirror API schemas, no ORM dependency)
# ---------------------------------------------------------------------------


class SyncJobItem(BaseModel):
    """Sync job data returned by GET /api/sync-jobs."""

    id: UUID
    name: str
    is_active: bool
    target_device_id: UUID
    strategy: str
    query: str | None
    count: int
    random_pick: bool
    overfetch_multiplier: int
    album_ids: list[str] | None
    person_ids: list[str] | None
    tag_ids: list[str] | None
    is_favorite: bool | None
    city: str | None
    state: str | None
    country: str | None
    taken_after: datetime | None
    taken_before: datetime | None
    rating: int | None
    min_color_score: float
    min_vibrancy_score: float


class DeviceItem(BaseModel):
    """Device data returned by GET /api/devices."""

    id: UUID
    device_id: str
    display_width: int
    display_height: int
    display_orientation: str
    display_model: str
    current_image_id: UUID | None


class ImageItem(BaseModel):
    """Image data returned by the API."""

    id: UUID
    source_name: str
    source_id: str | None = None
    sync_job_name: str | None = None
    source_url: str | None
    storage_path: str
    expires_at: datetime | None


class ImageRegisterPayload(BaseModel):
    """Payload for POST /api/images/register."""

    source_name: str = "immich"
    source_id: str | None = None
    sync_job_name: str | None = None
    storage_path: str
    source_url: str | None = None
    title: str | None = None
    description: str | None = None
    author: str | None = None
    tags: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    is_portrait: bool = False
    display_duration_seconds: int = 600
    priority: int = 5
    expires_at: datetime | None = None


class ImageUpdatePayload(BaseModel):
    """Payload for PUT /api/images/{id}."""

    title: str | None = None
    description: str | None = None
    author: str | None = None
    tags: str | None = None
    original_width: int | None = None
    original_height: int | None = None
    is_portrait: bool | None = None
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class DisplayAPIError(Exception):
    """Raised when the Display API returns an unexpected error."""


class DisplayAPINotFoundError(DisplayAPIError):
    """Raised when the Display API returns 404."""


class DisplayAPIClient:
    """Async HTTP client for the Inky Image Display REST API.

    Provides typed methods for all operations the sync service needs,
    replacing direct SQLite access.
    """

    def __init__(self, config: APIClientConfig, logger: logging.Logger) -> None:
        """Initialise the client.

        Args:
            config: API connection settings.
            logger: Logger instance.

        """
        self._base_url = str(config.base_url).rstrip("/")
        self._logger = logger
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(config.timeout_seconds),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise DisplayAPINotFoundError(f"Not found: {path}")
        response.raise_for_status()
        return response

    # --- Sync Jobs ---

    async def get_active_sync_jobs(self) -> list[SyncJobItem]:
        """Fetch all active sync jobs."""
        response = await self._request("GET", "/api/sync-jobs", params={"is_active": "true"})
        return [SyncJobItem.model_validate(j) for j in response.json()]

    # --- Images ---

    async def find_image_by_source(self, source_name: str, source_id: str) -> ImageItem | None:
        """Return the image matching (source_name, source_id), or None."""
        response = await self._request(
            "GET",
            "/api/images",
            params={"source_name": source_name, "source_id": source_id, "limit": 1},
        )
        items = response.json()
        return ImageItem.model_validate(items[0]) if items else None

    async def list_images(
        self,
        source_name: str | None = None,
        expires_before: datetime | None = None,
        limit: int = 1000,
    ) -> list[ImageItem]:
        """List images with optional filters."""
        params: dict[str, str | int] = {"limit": limit}
        if source_name is not None:
            params["source_name"] = source_name
        if expires_before is not None:
            params["expires_before"] = expires_before.isoformat()
        response = await self._request("GET", "/api/images", params=params)
        return [ImageItem.model_validate(i) for i in response.json()]

    async def register_image(self, payload: ImageRegisterPayload) -> ImageItem:
        """Register a pre-uploaded S3 image in the database."""
        response = await self._request("POST", "/api/images/register", json=payload.model_dump(mode="json"))
        return ImageItem.model_validate(response.json())

    async def update_image(self, image_id: UUID, payload: ImageUpdatePayload) -> ImageItem:
        """Update metadata for an existing image."""
        response = await self._request(
            "PUT",
            f"/api/images/{image_id}",
            json=payload.model_dump(mode="json", exclude_unset=True),
        )
        return ImageItem.model_validate(response.json())

    async def delete_image(self, image_id: UUID) -> None:
        """Delete an image (DB record + S3 object) via the API."""
        await self._request("DELETE", f"/api/images/{image_id}")

    # --- Devices ---

    async def get_devices(self, id: UUID | None = None) -> list[DeviceItem]:
        """Fetch devices, optionally filtered by primary-key UUID."""
        params: dict[str, str] = {}
        if id is not None:
            params["id"] = str(id)
        response = await self._request("GET", "/api/devices", params=params)
        return [DeviceItem.model_validate(d) for d in response.json()]
