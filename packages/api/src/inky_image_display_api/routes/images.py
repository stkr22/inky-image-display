"""REST endpoints for image management."""

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from inky_image_display_shared.models import Image
from PIL import Image as PILImage
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import ImageCreate, ImageRegister, ImageResponse, ImageUpdate

router = APIRouter(prefix="/api/images", tags=["images"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[ImageResponse])
async def list_images(
    request: Request,
    source_name: str | None = None,
    source_id: str | None = None,
    is_portrait: bool | None = None,
    source_url: str | None = None,
    source_url_prefix: str | None = None,
    expires_before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Image]:
    """List images with optional filters.

    Args:
        request: Incoming HTTP request.
        source_name: Filter by source type (e.g. "immich", "manual").
        source_id: Filter by stable source identifier (e.g. an Immich asset UUID).
        is_portrait: Filter by orientation.
        source_url: Filter by exact source URL.
        source_url_prefix: Filter by source URL prefix (LIKE match).
        expires_before: Return only images expiring before this datetime.
        limit: Max results to return.
        offset: Number of results to skip.

    """
    async with AsyncSession(request.app.state.engine) as session:
        query = select(Image)
        if source_name is not None:
            query = query.where(Image.source_name == source_name)
        if source_id is not None:
            query = query.where(Image.source_id == source_id)
        if is_portrait is not None:
            query = query.where(Image.is_portrait == is_portrait)
        if source_url is not None:
            query = query.where(Image.source_url == source_url)
        if source_url_prefix is not None:
            query = query.where(col(Image.source_url).like(f"{source_url_prefix}%"))
        if expires_before is not None:
            query = query.where(
                col(Image.expires_at).isnot(None),
                col(Image.expires_at) < expires_before,
            )
        query = query.offset(offset).limit(limit)
        result = await session.exec(query)
        return list(result.all())


# /register must come before /{image_id} to avoid path conflict
@router.post("/register", response_model=ImageResponse, status_code=201)
async def register_image(request: Request, body: ImageRegister) -> Image:
    """Register an image that was pre-uploaded directly to S3.

    Unlike the upload endpoint, this accepts a JSON body with a pre-existing
    ``storage_path`` and does not perform any S3 upload.
    """
    image = Image(
        source_name=body.source_name,
        source_id=body.source_id,
        sync_job_name=body.sync_job_name,
        storage_path=body.storage_path,
        source_url=body.source_url,
        title=body.title,
        description=body.description,
        author=body.author,
        tags=body.tags,
        original_width=body.original_width,
        original_height=body.original_height,
        is_portrait=body.is_portrait,
        display_duration_seconds=body.display_duration_seconds,
        priority=body.priority,
        expires_at=body.expires_at,
    )
    async with AsyncSession(request.app.state.engine) as session:
        session.add(image)
        await session.commit()
        await session.refresh(image)
    logger.info("Registered image %s (%s)", image.id, image.storage_path)
    return image


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(request: Request, image_id: UUID) -> Image:
    """Get a single image by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Image).where(col(Image.id) == image_id))
        image = result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")
        return image


@router.post("", response_model=ImageResponse, status_code=201)
async def upload_image(
    request: Request,
    file: UploadFile,
    metadata: Annotated[str, Form()] = "{}",
) -> Image:
    """Upload an image file with JSON metadata.

    The ``metadata`` form field should contain a JSON string matching
    the ``ImageCreate`` schema.
    """
    parsed = ImageCreate.model_validate(json.loads(metadata))
    data = await file.read()

    image_uuid = uuid4()
    storage_path = f"{parsed.source_name}/{image_uuid}.jpg"

    # Determine dimensions from the uploaded image; the orientation flag
    # reflects the intended target device and may be overridden by metadata.
    pil_image = PILImage.open(BytesIO(data))
    width, height = pil_image.size
    is_portrait = parsed.is_portrait if parsed.is_portrait is not None else height > width

    # Upload to S3
    s3 = request.app.state.s3_service
    content_type = file.content_type or "image/jpeg"
    s3.upload_image(storage_path, data, content_type)

    # Persist metadata
    image = Image(
        id=image_uuid,
        source_name=parsed.source_name,
        storage_path=storage_path,
        title=parsed.title,
        description=parsed.description,
        author=parsed.author,
        display_duration_seconds=parsed.display_duration_seconds,
        priority=parsed.priority,
        original_width=width,
        original_height=height,
        is_portrait=is_portrait,
        tags=parsed.tags,
    )
    async with AsyncSession(request.app.state.engine) as session:
        session.add(image)
        await session.commit()
        await session.refresh(image)

    logger.info("Uploaded image %s (%s)", image.id, storage_path)
    return image


@router.put("/{image_id}", response_model=ImageResponse)
async def update_image(request: Request, image_id: UUID, body: ImageUpdate) -> Image:
    """Update metadata for an existing image.

    Only fields present in the request body are updated.
    """
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Image).where(col(Image.id) == image_id))
        image = result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")

        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(image, key, value)

        session.add(image)
        await session.commit()
        await session.refresh(image)

    logger.info("Updated image %s", image_id)
    return image


@router.delete("/{image_id}", status_code=204)
async def delete_image(request: Request, image_id: UUID) -> None:
    """Delete an image from the database and S3."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Image).where(col(Image.id) == image_id))
        image = result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")

        # Remove from S3
        try:
            request.app.state.s3_service.delete_object(image.storage_path)
        except Exception:
            logger.warning("Failed to delete S3 object %s", image.storage_path)

        await session.delete(image)
        await session.commit()
