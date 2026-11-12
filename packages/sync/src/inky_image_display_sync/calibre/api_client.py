"""Calibre-specific Display API extensions.

Adds the ``/api/calibre/*`` job endpoints on top of the shared
:class:`~inky_image_display_sync.api_client.DisplayAPIClient`. Prompt blocks
and presets are reused from the Gemini client rather than redeclared — the
bookshelf prompts are ordinary presets.
"""

from __future__ import annotations

from inky_image_display_shared.schemas.responses import CalibreSyncJobResponse

from inky_image_display_sync.gemini.api_client import GeminiDisplayAPIClient


class CalibreDisplayAPIClient(GeminiDisplayAPIClient):
    """Display API client with Calibre job methods added.

    Extends the Gemini client because a bookshelf run needs the same prompt
    block and preset lookups, plus image registration and processing from the
    base class.
    """

    async def get_active_calibre_jobs(self) -> list[CalibreSyncJobResponse]:
        """Fetch all active bookshelf jobs (schedule ignored — for --all runs)."""
        response = await self._request("GET", "/api/calibre/jobs", params={"is_active": "true"})
        return [CalibreSyncJobResponse.model_validate(j) for j in response.json()]

    async def get_used_book_ids(self) -> set[int]:
        """Calibre ids of books already on a live image, whichever job made it."""
        response = await self._request("GET", "/api/calibre/jobs/used-books")
        return {int(book_id) for book_id in response.json()}

    async def get_due_calibre_jobs(self) -> list[CalibreSyncJobResponse]:
        """Preview due jobs without claiming them (dry-run mode)."""
        response = await self._request("GET", "/api/calibre/jobs", params={"due": "true"})
        return [CalibreSyncJobResponse.model_validate(j) for j in response.json()]

    async def claim_due_calibre_jobs(self) -> list[CalibreSyncJobResponse]:
        """Claim due jobs: the API advances their schedules on hand-out."""
        response = await self._request("POST", "/api/calibre/jobs/claim-due")
        return [CalibreSyncJobResponse.model_validate(j) for j in response.json()]


__all__ = ["CalibreDisplayAPIClient"]
