"""Calibre-specific Display API extensions.

Adds the ``/api/calibre/*`` job endpoints on top of the shared
:class:`~inky_image_display_sync.api_client.DisplayAPIClient`. Prompt blocks
and presets are reused from the Gemini client rather than redeclared — the
bookshelf prompts are ordinary presets.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 -- pydantic needs this at runtime

from pydantic import BaseModel

from inky_image_display_sync.gemini.api_client import GeminiDisplayAPIClient


class CalibreSyncJobItem(BaseModel):
    """Calibre bookshelf job data returned by GET /api/calibre/jobs."""

    id: UUID
    name: str
    is_active: bool
    mode: str
    target_device_profile_id: UUID
    prompt_preset_id: UUID
    tags: list[str]
    languages: list[str]
    series: list[str]
    authors: list[str]
    min_rating: int | None
    books_per_shelf: int
    images_per_run: int
    retention_days: int | None
    verify_spines: bool
    max_attempts: int


class CalibreDisplayAPIClient(GeminiDisplayAPIClient):
    """Display API client with Calibre job methods added.

    Extends the Gemini client because a bookshelf run needs the same prompt
    block and preset lookups, plus image registration and processing from the
    base class.
    """

    async def get_active_calibre_jobs(self) -> list[CalibreSyncJobItem]:
        """Fetch all active bookshelf jobs (schedule ignored — for --all runs)."""
        response = await self._request("GET", "/api/calibre/jobs", params={"is_active": "true"})
        return [CalibreSyncJobItem.model_validate(j) for j in response.json()]

    async def get_due_calibre_jobs(self) -> list[CalibreSyncJobItem]:
        """Preview due jobs without claiming them (dry-run mode)."""
        response = await self._request("GET", "/api/calibre/jobs", params={"due": "true"})
        return [CalibreSyncJobItem.model_validate(j) for j in response.json()]

    async def claim_due_calibre_jobs(self) -> list[CalibreSyncJobItem]:
        """Claim due jobs: the API advances their schedules on hand-out."""
        response = await self._request("POST", "/api/calibre/jobs/claim-due")
        return [CalibreSyncJobItem.model_validate(j) for j in response.json()]


__all__ = ["CalibreDisplayAPIClient", "CalibreSyncJobItem"]
