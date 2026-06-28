"""Immich-specific Display API extensions.

Adds the ``/api/sync-jobs`` endpoint plus its payload model on top of the
shared :class:`~inky_image_display_sync.api_client.DisplayAPIClient`. Only
Immich-flavoured code lives here — generic image and device methods are
inherited from the base class.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- pydantic needs this at runtime
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel

from inky_image_display_sync.api_client import (
    DisplayAPIClient,
    DisplayAPIError,
    DisplayAPINotFoundError,
    ImageItem,
    ImageRegisterPayload,
    ImageUpdatePayload,
)


class SyncJobItem(BaseModel):
    """Sync job data returned by GET /api/sync-jobs."""

    id: UUID
    name: str
    is_active: bool
    target_device_profile_id: UUID
    orientation: str | None
    strategy: str
    query: str | None
    count: int
    max_images: int
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


class ImmichDisplayAPIClient(DisplayAPIClient):
    """Display API client with Immich-specific methods added."""

    async def get_active_sync_jobs(self) -> list[SyncJobItem]:
        """Fetch all active Immich sync jobs."""
        response = await self._request("GET", "/api/sync-jobs", params={"is_active": "true"})
        return [SyncJobItem.model_validate(j) for j in response.json()]


__all__ = [
    "DisplayAPIError",
    "DisplayAPINotFoundError",
    "ImageItem",
    "ImageRegisterPayload",
    "ImageUpdatePayload",
    "ImmichDisplayAPIClient",
    "SyncJobItem",
]
