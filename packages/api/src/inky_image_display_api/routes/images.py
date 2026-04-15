"""REST endpoints for image management."""

import json
import logging
from io import BytesIO
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from inky_image_display_shared.models import Image
from PIL import Image as PILImage
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import ImageCreate, ImageResponse

router = APIRouter(prefix="/api/images", tags=["images"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[ImageResponse])
async def list_images(
    request: Request,
    source_name: str | None = None,
    is_portrait: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Image]:
    """List images with optional filters.

    Args:
        request: Incoming HTTP request.
        source_name: Filter by source.
        is_portrait: Filter by orientation.
        limit: Max results to return.
        offset: Number of results to skip.

    """
    async with AsyncSession(request.app.state.engine) as session:
        query = select(Image)
        if source_name is not None:
            query = query.where(Image.source_name == source_name)
        if is_portrait is not None:
            query = query.where(Image.is_portrait == is_portrait)
        query = query.offset(offset).limit(limit)
        result = await session.exec(query)
        return list(result.all())


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

    # Determine dimensions from the uploaded image
    pil_image = PILImage.open(BytesIO(data))
    width, height = pil_image.size
    is_portrait = height > width

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
