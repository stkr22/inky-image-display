"""Gemini-specific Display API extensions.

Adds the ``/api/genai/*`` endpoints (blocks, presets, jobs) on top of the
shared :class:`~inky_image_display_sync.api_client.DisplayAPIClient`. Generic
image and device methods are inherited from the base class — only AI-flavoured
code lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from inky_image_display_shared.schemas.responses import (
    GeminiSyncJobResponse,
    PromptBlockResponse,
    PromptPresetResponse,
)

from inky_image_display_sync.api_client import DisplayAPIClient

if TYPE_CHECKING:
    from uuid import UUID


class GeminiDisplayAPIClient(DisplayAPIClient):
    """Display API client with Gemini-specific methods added."""

    async def get_active_gemini_jobs(self) -> list[GeminiSyncJobResponse]:
        """Fetch all active Gemini sync jobs (schedule ignored — for --all runs)."""
        response = await self._request("GET", "/api/genai/jobs", params={"is_active": "true"})
        return [GeminiSyncJobResponse.model_validate(j) for j in response.json()]

    async def get_due_gemini_jobs(self) -> list[GeminiSyncJobResponse]:
        """Preview due jobs without claiming them (dry-run mode)."""
        response = await self._request("GET", "/api/genai/jobs", params={"due": "true"})
        return [GeminiSyncJobResponse.model_validate(j) for j in response.json()]

    async def claim_due_gemini_jobs(self) -> list[GeminiSyncJobResponse]:
        """Claim due jobs: the API advances their schedules on hand-out."""
        response = await self._request("POST", "/api/genai/jobs/claim-due")
        return [GeminiSyncJobResponse.model_validate(j) for j in response.json()]

    async def get_prompt_preset(self, preset_id: UUID) -> PromptPresetResponse:
        """Fetch a single prompt preset by id."""
        response = await self._request("GET", f"/api/genai/presets/{preset_id}")
        return PromptPresetResponse.model_validate(response.json())

    async def list_prompt_blocks(self) -> list[PromptBlockResponse]:
        """Fetch all prompt blocks."""
        response = await self._request("GET", "/api/genai/blocks")
        return [PromptBlockResponse.model_validate(b) for b in response.json()]


__all__ = ["GeminiDisplayAPIClient"]
