"""FastAPI router that accepts browser uploads and forwards them to the API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from inky_image_display_ui.api_client import ApiError

if TYPE_CHECKING:
    from inky_image_display_ui.api_client import ApiClient

router = APIRouter(tags=["upload"])


@router.post("/internal/upload")
async def upload_image(
    request: Request,
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form()],
) -> dict[str, Any]:
    """Accept a multipart upload from the browser and forward it to the API.

    The Flet ``FilePicker`` control uploads to a server-side endpoint; this
    handler parses the ``metadata`` JSON string, reads the uploaded file into
    memory, and delegates to :meth:`ApiClient.upload_image`.
    """
    try:
        metadata_obj = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid metadata JSON: {exc}") from exc
    if not isinstance(metadata_obj, dict):
        raise HTTPException(status_code=422, detail="metadata must be a JSON object")

    payload = await file.read()
    filename = file.filename or "upload.bin"

    client: ApiClient = request.app.state.api_client
    try:
        return await client.upload_image(payload, filename, metadata_obj)
    except ApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail or "Upload failed") from exc
