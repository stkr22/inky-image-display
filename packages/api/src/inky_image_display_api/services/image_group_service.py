"""Image-group helpers shared by the group, display-job and grid routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inky_image_display_shared.models import Image
from inky_image_display_shared.schemas.responses import ImageGroupResponse, ImageResponse
from sqlmodel import col, select

from inky_image_display_api.services.queue_service import group_images

if TYPE_CHECKING:
    from uuid import UUID

    from inky_image_display_shared.models import ImageGroup
    from sqlmodel.ext.asyncio.session import AsyncSession


async def group_response(session: AsyncSession, group: ImageGroup) -> ImageGroupResponse:
    """Serialize a group with its member images in frame order."""
    response = ImageGroupResponse.model_validate(group)
    response.images = [ImageResponse.model_validate(image) for image in await group_images(session, group.id)]
    return response


async def set_group_members(session: AsyncSession, group_id: UUID, image_ids: list[UUID]) -> None:
    """Replace a group's membership with ``image_ids`` in list order.

    Dropped images return to the plain library (their grid-pool link was
    cleared when they joined, so they re-enter solo rotation). Does not
    commit.
    """
    current = await session.exec(select(Image).where(col(Image.group_id) == group_id))
    wanted = {image_id: position for position, image_id in enumerate(image_ids)}
    for image in current.all():
        if image.id not in wanted:
            image.group_id = None
            session.add(image)
    if not image_ids:
        return
    images = await session.exec(select(Image).where(col(Image.id).in_(list(wanted))))
    for image in images.all():
        image.group_id = group_id
        image.queue_position = wanted[image.id]
        # Curated groups are full-canvas frame sequences; only the worker
        # sets slot addresses on the images it generates.
        session.add(image)
