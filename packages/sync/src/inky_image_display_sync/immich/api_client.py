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
    # Defaults keep the worker compatible with an API that predates match modes.
    album_match_mode: str = "all"
    person_match_mode: str = "all"
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
        """Fetch all active Immich sync jobs (schedule ignored — for --all runs)."""
        response = await self._request("GET", "/api/sync-jobs", params={"is_active": "true"})
        return [SyncJobItem.model_validate(j) for j in response.json()]

    async def get_due_sync_jobs(self) -> list[SyncJobItem]:
        """Preview due jobs without claiming them (dry-run mode)."""
        response = await self._request("GET", "/api/sync-jobs", params={"due": "true"})
        return [SyncJobItem.model_validate(j) for j in response.json()]

    async def claim_due_sync_jobs(self) -> list[SyncJobItem]:
        """Claim due jobs: the API advances their schedules on hand-out."""
        response = await self._request("POST", "/api/sync-jobs/claim-due")
        return [SyncJobItem.model_validate(j) for j in response.json()]


__all__ = [
    "DisplayAPIError",
    "ImageItem",
    "ImageRegisterPayload",
    "ImageUpdatePayload",
    "ImmichDisplayAPIClient",
    "SyncJobItem",
]
