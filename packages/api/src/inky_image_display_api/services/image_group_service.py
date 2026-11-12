"""Image-group helpers shared by the group, display-job and grid routes."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from inky_image_display_shared.models import Image
from inky_image_display_shared.schemas.responses import ImageGroupResponse, ImageResponse
from sqlmodel import col, select

if TYPE_CHECKING:
    from uuid import UUID

    from inky_image_display_shared.models import ImageGroup
    from sqlmodel.ext.asyncio.session import AsyncSession

    from inky_image_display_api.schemas import GroupMemberAssignment


async def group_response(session: AsyncSession, group: ImageGroup) -> ImageGroupResponse:
    """Serialize a group with its member images in frame order."""
    return (await group_responses(session, [group]))[0]


async def group_responses(session: AsyncSession, groups: list[ImageGroup]) -> list[ImageGroupResponse]:
    """Serialize many groups with one image query instead of one per group.

    Ordering matches :func:`queue_service.group_images` (frame order).
    """
    by_group: dict[UUID, list[Image]] = defaultdict(list)
    if groups:
        result = await session.exec(
            select(Image)
            .where(col(Image.group_id).in_([g.id for g in groups]))
            .order_by(col(Image.queue_position), col(Image.created_at))
        )
        for image in result.all():
            if image.group_id is not None:
                by_group[image.group_id].append(image)
    responses = []
    for group in groups:
        response = ImageGroupResponse.model_validate(group)
        response.images = [ImageResponse.model_validate(image) for image in by_group[group.id]]
        responses.append(response)
    return responses


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
