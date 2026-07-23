"""Display-job specific Display API extensions.

Adds the claim / render / image-group endpoints on top of the shared
:class:`~inky_image_display_sync.api_client.DisplayAPIClient`. The Gemini
prompt-library methods are inherited from the Gemini client because MOTD
illustrations reuse the same preset machinery.
"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 -- pydantic needs this at runtime

from inky_image_display_shared.schemas.responses import (
    DisplayJobClaim as DisplayJobClaimItem,
)
from inky_image_display_shared.schemas.responses import (
    DisplayJobClaimSlot as DisplayJobSlotItem,
)
from pydantic import BaseModel

from inky_image_display_sync.gemini.api_client import GeminiDisplayAPIClient


class ImageGroupCreatePayload(BaseModel):
    """Payload for POST /api/image-groups."""

    name: str
    target_grid_id: UUID
    display_job_id: UUID
    description: str | None = None
    source_url: str | None = None


class ImageGroupItem(BaseModel):
    """Image group returned by the API (id is all the worker needs)."""

    id: UUID
    name: str


class DisplayJobAPIClient(GeminiDisplayAPIClient):
    """Display API client with display-job worker methods added."""

    async def claim_due_display_jobs(self) -> list[DisplayJobClaimItem]:
        """Claim due display jobs; the API advances their schedules on hand-out."""
        response = await self._request("POST", "/api/display-jobs/claim-due")
        return [DisplayJobClaimItem.model_validate(j) for j in response.json()]

    async def render_part(self, part: str, width: int, height: int, story: dict[str, str | None]) -> bytes:
        """Render one story part at one panel size; returns JPEG bytes."""
        response = await self._request(
            "POST",
            "/api/display-jobs/render-part",
            json={"part": part, "width": width, "height": height, **story},
        )
        return response.content

    async def create_image_group(self, payload: ImageGroupCreatePayload) -> ImageGroupItem:
        """Create the group that will hold this run's rendered screens."""
        response = await self._request("POST", "/api/image-groups", json=payload.model_dump(mode="json"))
        return ImageGroupItem.model_validate(response.json())

    async def delete_image_group(self, group_id: UUID) -> None:
        """Delete a group and its images (cleanup of a failed run)."""
        await self._request("DELETE", f"/api/image-groups/{group_id}", params={"delete_images": "true"})


__all__ = [
    "DisplayJobAPIClient",
    "DisplayJobClaimItem",
    "DisplayJobSlotItem",
    "ImageGroupCreatePayload",
    "ImageGroupItem",
]
