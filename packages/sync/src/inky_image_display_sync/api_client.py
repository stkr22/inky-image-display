"""Shared HTTP client for the Inky Image Display REST API.

Holds the generic methods (devices, images, register_image, ...) that every
sync source needs. Per-source extensions live next to their own module:

- Immich-specific endpoints (sync_jobs): ``inky_image_display_sync.immich.api_client``
- Gemini-specific endpoints (prompt library, gemini jobs):
  ``inky_image_display_sync.gemini.api_client``

Both extend :class:`DisplayAPIClient` so they reuse the same ``httpx`` session
without duplicating connection setup or error handling.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    import logging
    from datetime import datetime
    from uuid import UUID

    from inky_image_display_sync.immich.config import APIClientConfig
else:
    from datetime import datetime  # noqa: TC003 -- pydantic needs this at runtime
    from uuid import UUID  # noqa: TC003


class DeviceProfileItem(BaseModel):
    """Device profile data returned by GET /api/device-profiles."""

    id: UUID
    key: str
    name: str
    width: int
    height: int
    model: str
    is_default: bool


class DeviceItem(BaseModel):
    """Device data returned by GET /api/devices."""

    id: UUID
    device_id: str
    device_profile_id: UUID
    display_orientation: str
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


class DisplayAPIError(Exception):
    """Raised when the Display API returns an unexpected error."""


class DisplayAPINotFoundError(DisplayAPIError):
    """Raised when the Display API returns 404."""


class DisplayAPIClient:
    """Async HTTP client for the Inky Image Display REST API.

    Provides generic methods (images, devices) shared by all sync sources.
    Per-source extensions subclass this to add their endpoints.
    """

    def __init__(self, config: APIClientConfig, logger: logging.Logger) -> None:
        """Initialise the client."""
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

    # --- Device profiles ---

    async def get_device_profile(self, profile_id: UUID) -> DeviceProfileItem:
        """Fetch a single device profile by primary-key UUID."""
        response = await self._request("GET", f"/api/device-profiles/{profile_id}")
        return DeviceProfileItem.model_validate(response.json())

    async def get_device_profiles(self) -> list[DeviceProfileItem]:
        """Fetch all seeded device profiles."""
        response = await self._request("GET", "/api/device-profiles")
        return [DeviceProfileItem.model_validate(p) for p in response.json()]
