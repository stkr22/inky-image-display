"""E-ink render preview endpoints.

``GET /api/images/{id}/eink-preview`` simulates the Spectra 6 panel
rendering of a stored image; ``POST /api/images/eink-preview`` does the
same for not-yet-uploaded bytes so the upload/crop dialog can preview
before committing.

Handlers are deliberately *sync* ``def`` like the media proxy — FastAPI
runs them in the threadpool, keeping Pillow and the blocking MinIO SDK off
the event loop that drives MQTT.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003 -- FastAPI resolves the path-param annotation at runtime

from anyio import to_thread
from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile
from inky_image_display_shared.models import Image
from minio.error import S3Error
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.services.eink_preview import DEFAULT_SATURATION, render_eink_preview
from inky_image_display_api.services.image_deletion import eink_preview_key
from inky_image_display_api.services.s3_service import stat_or_none

if TYPE_CHECKING:
    from inky_image_display_api.services.s3_service import S3Service

router = APIRouter(prefix="/api/images", tags=["images"])
logger = logging.getLogger(__name__)


# Previews are cached under the media proxy's reserved thumbs/ namespace so
# the proxy never serves them directly; image deletion removes them with the
# other derived objects. Saturation is snapped to one decimal to bound cache
# variants.
def _snap_saturation(saturation: float) -> float:
    return min(1.0, max(0.0, round(saturation, 1)))


def _cache_key(storage_path: str, saturation: float) -> str:
    return eink_preview_key(storage_path, round(saturation * 10))


def _png_response(data: bytes, request: Request) -> Response:
    max_age = request.app.state.settings.media_cache_max_age
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": f"public, max-age={max_age}",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


# Must be declared before any /{image_id} sibling matching could swallow
# the literal path (mirrors the /register comment in images.py).
@router.post("/eink-preview")
def eink_preview_upload(
    request: Request,
    file: UploadFile,
    saturation: Annotated[float, Form()] = DEFAULT_SATURATION,
) -> Response:
    """Render the e-ink simulation for uploaded bytes (nothing is stored)."""
    data = file.file.read()
    # Same memory ceiling as the media thumbnails: this is a sync handler in
    # the threadpool, so the threading gate applies.
    try:
        with request.app.state.thumb_gate:
            preview = render_eink_preview(data, _snap_saturation(saturation))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="File is not a decodable image") from exc
    return _png_response(preview, request)


@router.get("/{image_id}/eink-preview")
async def eink_preview(request: Request, image_id: UUID, saturation: float = DEFAULT_SATURATION) -> Response:
    """Render (and cache) the e-ink simulation of a stored image."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Image).where(col(Image.id) == image_id))
        image = result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")
        storage_path = image.storage_path

    snapped = _snap_saturation(saturation)
    s3: S3Service = request.app.state.s3_service
    cache_key = _cache_key(storage_path, snapped)

    # S3 and Pillow work is blocking; run it off the event loop. Only a real
    # not-found counts as a cache miss — an S3 outage must not turn every
    # preview request into a full-size decode.
    def _cached() -> bytes | None:
        if stat_or_none(s3, cache_key) is None:
            return None
        return s3.get_object_bytes(cache_key)

    def _render() -> bytes:
        preview = render_eink_preview(s3.get_object_bytes(storage_path), snapped)
        try:
            s3.upload_image(cache_key, preview, "image/png")
        except S3Error:
            logger.warning("Failed to cache e-ink preview %s", cache_key)
        return preview

    try:
        data = await to_thread.run_sync(_cached)
        if data is None:
            async with request.app.state.process_gate:
                data = await to_thread.run_sync(_render)
    except S3Error as exc:
        raise HTTPException(status_code=502, detail="Upstream storage error") from exc
    return _png_response(data, request)
