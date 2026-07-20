"""REST endpoints for image groups.

Operators bundle existing library images into a group for a grid; the
display worker registers each run's generated screens as a group too.
Either way the group enters the grid's content queue and its images leave
regular rotation.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import Image, ImageGroup
from inky_image_display_shared.schemas.responses import ImageGroupResponse
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import ImageGroupCreate, ImageGroupUpdate
from inky_image_display_api.services.image_group_service import group_response, set_group_members

router = APIRouter(prefix="/api/image-groups", tags=["image-groups"])
logger = logging.getLogger(__name__)


async def _get_group_or_404(session: AsyncSession, group_id: UUID) -> ImageGroup:
    group = await session.get(ImageGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Image group not found")
    return group


@router.get("")
async def list_image_groups(request: Request, target_grid_id: UUID | None = None) -> list[ImageGroupResponse]:
    """List groups (optionally one grid's), newest first, with images."""
    async with AsyncSession(request.app.state.engine) as session:
        query = select(ImageGroup).order_by(col(ImageGroup.created_at).desc())
        if target_grid_id is not None:
            query = query.where(col(ImageGroup.target_grid_id) == target_grid_id)
        result = await session.exec(query)
        return [await group_response(session, group) for group in result.all()]


@router.post("", status_code=201)
async def create_image_group(request: Request, body: ImageGroupCreate) -> ImageGroupResponse:
    """Create a group; ``members`` assign images to grid panels."""
    async with AsyncSession(request.app.state.engine) as session:
        group = ImageGroup(
            name=body.name,
            target_grid_id=body.target_grid_id,
            display_job_id=body.display_job_id,
            description=body.description,
            source_url=body.source_url,
        )
        session.add(group)
        await session.flush()
        await set_group_members(session, group.id, body.members)
        await session.commit()
        await session.refresh(group)
        logger.info("Created image group %s (%s) with %d image(s)", group.id, group.name, len(body.members))
        return await group_response(session, group)


@router.get("/{group_id}")
async def get_image_group(request: Request, group_id: UUID) -> ImageGroupResponse:
    """Fetch a single group with its images."""
    async with AsyncSession(request.app.state.engine) as session:
        group = await _get_group_or_404(session, group_id)
        return await group_response(session, group)


@router.put("/{group_id}")
async def update_image_group(request: Request, group_id: UUID, body: ImageGroupUpdate) -> ImageGroupResponse:
    """Rename or re-target a group, or replace its members/slots."""
    async with AsyncSession(request.app.state.engine) as session:
        group = await _get_group_or_404(session, group_id)
        if group.display_job_id is not None:
            # Worker-generated groups are a run's immutable output — the
            # job re-creates them; operators can only delete.
            raise HTTPException(status_code=409, detail="Generated groups are read-only; delete instead")
        if body.name is not None:
            group.name = body.name
        if body.clear_target_grid:
            group.target_grid_id = None
        elif body.target_grid_id is not None:
            group.target_grid_id = body.target_grid_id
        if body.description is not None:
            group.description = body.description
        group.updated_at = utcnow()
        session.add(group)
        if body.members is not None:
            await set_group_members(session, group.id, body.members)
        await session.commit()
        await session.refresh(group)
        return await group_response(session, group)


@router.delete("/{group_id}", status_code=204)
async def delete_image_group(request: Request, group_id: UUID, delete_images: bool = False) -> None:
    """Delete a group.

    By default member images return to the plain library; pass
    ``delete_images=true`` to remove them (and their S3 objects) too —
    that is what pruning worker-generated screens wants.
    """
    async with AsyncSession(request.app.state.engine) as session:
        group = await _get_group_or_404(session, group_id)
        images = await session.exec(select(Image).where(col(Image.group_id) == group_id))
        for image in images.all():
            if delete_images:
                try:
                    request.app.state.s3_service.delete_object(image.storage_path)
                except Exception:
                    logger.warning("Failed to delete S3 object %s", image.storage_path)
                await session.delete(image)
            else:
                image.group_id = None
                session.add(image)
        await session.delete(group)
        await session.commit()
    logger.info("Deleted image group %s (delete_images=%s)", group_id, delete_images)
