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

    from inky_image_display_api.schemas import GroupMemberAssignment


async def group_response(session: AsyncSession, group: ImageGroup) -> ImageGroupResponse:
    """Serialize a group with its member images in frame order."""
    response = ImageGroupResponse.model_validate(group)
    response.images = [ImageResponse.model_validate(image) for image in await group_images(session, group.id)]
    return response


async def set_group_members(session: AsyncSession, group_id: UUID, members: list[GroupMemberAssignment]) -> None:
    """Replace a group's membership and panel (slot) assignments.

    List order becomes ``queue_position`` — the rotation order among
    members sharing a slot. Dropped images return to the plain library
    (their grid-pool link was cleared when they joined, so they re-enter
    solo rotation). Does not commit.
    """
    current = await session.exec(select(Image).where(col(Image.group_id) == group_id))
    wanted = {member.image_id: (position, member) for position, member in enumerate(members)}
    for image in current.all():
        if image.id not in wanted:
            image.group_id = None
            image.group_slot_row = None
            image.group_slot_col = None
            session.add(image)
    if not members:
        return
    images = await session.exec(select(Image).where(col(Image.id).in_(list(wanted))))
    for image in images.all():
        position, member = wanted[image.id]
        image.group_id = group_id
        image.queue_position = position
        image.group_slot_row = member.row
        image.group_slot_col = member.col
        session.add(image)
