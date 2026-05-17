"""On-demand image resize/crop endpoint used by sync workers."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from inky_image_display_api.services.image_processor import ImageProcessingError, ImageProcessor

router = APIRouter(prefix="/api/images", tags=["images"])
logger = logging.getLogger(__name__)


@router.post("/process")
async def process_image(
    file: Annotated[UploadFile, File()],
    width: Annotated[int, Form(gt=0)],
    height: Annotated[int, Form(gt=0)],
    upscale: Annotated[bool, Form()] = False,
) -> Response:
    """Resize and center-crop an uploaded image to ``width`` x ``height``.

    Returns the processed JPEG bytes. Responds 422 if the source image is
    smaller than the target on either axis and ``upscale`` is false — the
    sync workers map this to their ``SKIPPED_UNDERSIZED`` outcome.
    """
    data = await file.read()
    # PIL is synchronous and a multi-megapixel resize takes a few hundred ms;
    # off-load to a worker thread so the event loop keeps serving other
    # sync workers in parallel.
    try:
        processed = await asyncio.to_thread(
            ImageProcessor.process_for_display,
            data,
            width,
            height,
            upscale=upscale,
        )
    except ImageProcessingError as exc:
        logger.warning("Image processing failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if processed is None:
        raise HTTPException(
            status_code=422,
            detail="image too small for target dimensions",
        )
    return Response(content=processed, media_type="image/jpeg")
