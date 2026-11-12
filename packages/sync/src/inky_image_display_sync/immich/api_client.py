"""Immich-specific Display API extensions.

Adds the ``/api/sync-jobs`` endpoints on top of the shared
:class:`~inky_image_display_sync.api_client.DisplayAPIClient`. Only
Immich-flavoured code lives here — generic image and device methods are
inherited from the base class.
"""

from __future__ import annotations

from inky_image_display_shared.schemas.responses import SyncJobResponse

from inky_image_display_sync.api_client import DisplayAPIClient


class ImmichDisplayAPIClient(DisplayAPIClient):
    """Display API client with Immich-specific methods added."""

    async def get_active_sync_jobs(self) -> list[SyncJobResponse]:
        """Fetch all active Immich sync jobs (schedule ignored — for --all runs)."""
        response = await self._request("GET", "/api/sync-jobs", params={"is_active": "true"})
        return [SyncJobResponse.model_validate(j) for j in response.json()]

    async def get_due_sync_jobs(self) -> list[SyncJobResponse]:
        """Preview due jobs without claiming them (dry-run mode)."""
        response = await self._request("GET", "/api/sync-jobs", params={"due": "true"})
        return [SyncJobResponse.model_validate(j) for j in response.json()]

    async def claim_due_sync_jobs(self) -> list[SyncJobResponse]:
        """Claim due jobs: the API advances their schedules on hand-out."""
        response = await self._request("POST", "/api/sync-jobs/claim-due")
        return [SyncJobResponse.model_validate(j) for j in response.json()]


__all__ = ["ImmichDisplayAPIClient"]
