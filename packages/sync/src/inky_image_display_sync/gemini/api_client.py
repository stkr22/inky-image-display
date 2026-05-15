"""Gemini-specific Display API extensions.

Adds the ``/api/genai/*`` endpoints (blocks, presets, jobs) on top of the
shared :class:`~inky_image_display_sync.api_client.DisplayAPIClient`. Generic
image and device methods are inherited from the base class — only AI-flavoured
code lives here.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 -- pydantic needs this at runtime

from pydantic import BaseModel

from inky_image_display_sync.api_client import DisplayAPIClient


class GeminiSyncJobItem(BaseModel):
    """Gemini sync job data returned by GET /api/genai/jobs."""

    id: UUID
    name: str
    is_active: bool
    target_device_profile_id: UUID
    prompt_preset_id: UUID
    orientation: str
    subjects: list[str]
    images_per_subject: int
    retention_days: int | None


class PromptBlockItem(BaseModel):
    """Prompt block returned by GET /api/genai/blocks."""

    id: UUID
    kind: str
    name: str
    text: str
    is_default: bool


class PromptPresetItem(BaseModel):
    """Prompt preset returned by GET /api/genai/presets."""

    id: UUID
    name: str
    style_block_id: UUID
    palette_block_id: UUID
    legibility_block_id: UUID
    composition_block_id: UUID
    background_block_id: UUID
    model_name: str
    is_default: bool


class GeminiDisplayAPIClient(DisplayAPIClient):
    """Display API client with Gemini-specific methods added."""

    async def get_active_gemini_jobs(self) -> list[GeminiSyncJobItem]:
        """Fetch all active Gemini sync jobs."""
        response = await self._request("GET", "/api/genai/jobs", params={"is_active": "true"})
        return [GeminiSyncJobItem.model_validate(j) for j in response.json()]

    async def get_prompt_preset(self, preset_id: UUID) -> PromptPresetItem:
        """Fetch a single prompt preset by id."""
        response = await self._request("GET", f"/api/genai/presets/{preset_id}")
        return PromptPresetItem.model_validate(response.json())

    async def list_prompt_blocks(self) -> list[PromptBlockItem]:
        """Fetch all prompt blocks."""
        response = await self._request("GET", "/api/genai/blocks")
        return [PromptBlockItem.model_validate(b) for b in response.json()]


__all__ = [
    "GeminiDisplayAPIClient",
    "GeminiSyncJobItem",
    "PromptBlockItem",
    "PromptPresetItem",
]
