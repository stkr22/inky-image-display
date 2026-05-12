"""On-demand AI image generation endpoint.

Lives at ``POST /api/genai/generate`` alongside the other ``/api/genai/*``
resources (blocks, presets, jobs). The heavy lifting runs in a background
task so the HTTP request returns immediately with a task id.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from inky_image_display_api.schemas import ImageGenerateRequest, ImageGenerateResponse
from inky_image_display_api.services.generation_service import generate_and_publish

router = APIRouter(prefix="/api/genai", tags=["genai"])
logger = logging.getLogger(__name__)


@router.post("/generate", status_code=202)
async def generate_image(
    request: Request,
    body: ImageGenerateRequest,
    background_tasks: BackgroundTasks,
) -> ImageGenerateResponse:
    """Enqueue a Gemini generation for ``body.subject``.

    The Gemini API call, S3 upload, DB write and MQTT push happen in a
    background task because the model is slow (~10-20s); we don't want to
    keep the HTTP request open that long. Caller receives a ``task_id`` for
    correlating server logs.
    """
    settings = request.app.state.settings
    if settings.gemini_api_key is None:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured on the server.",
        )

    task_id = uuid4()
    background_tasks.add_task(
        generate_and_publish,
        request.app.state.engine,
        settings,
        request.app.state.s3_service,
        request.app.state.mqtt,
        task_id=task_id,
        subject=body.subject,
        target_device_id=body.target_device_id,
        preset_id=body.preset_id,
        is_portrait=body.is_portrait,
        push_immediately=body.push_immediately,
    )
    logger.info("Queued generation task %s for subject=%r", task_id, body.subject)
    return ImageGenerateResponse(task_id=task_id, status="queued")
