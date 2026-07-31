"""Browser-facing media proxy with on-the-fly thumbnails.

``GET /media/{object_key}`` streams an S3 object to the browser; with
``?w=<px>`` it serves a downscaled JPEG variant instead. Thumbnails are
generated lazily on first request and cached back into the bucket under
``thumbs/w{width}/{object_key}``, so there is no backfill job and no extra
work in the upload/sync paths.

Previously this proxy lived in the (now removed) NiceGUI UI service; it
moved here so the API is the single web-facing process. Endpoints are
deliberately *sync* ``def`` — FastAPI runs them in the threadpool, keeping
the blocking MinIO SDK and Pillow work off the event loop that handles
MQTT and device commands.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from minio.error import S3Error
from PIL import Image as PILImage

if TYPE_CHECKING:
    from inky_image_display_api.services.s3_service import S3Service

router = APIRouter(tags=["media"])
logger = logging.getLogger(__name__)

# Requested widths snap to this set so the cache holds a bounded number of
# variants per image instead of one per arbitrary pixel value.
ALLOWED_THUMB_WIDTHS = (240, 480, 960)
_THUMB_JPEG_QUALITY = 82
_THUMB_PREFIX = "thumbs"


def snap_width(requested: int) -> int:
    """Snap an arbitrary requested width to the nearest allowed variant."""
    return min(ALLOWED_THUMB_WIDTHS, key=lambda allowed: abs(allowed - requested))


def _thumb_key(object_key: str, width: int) -> str:
    return f"{_THUMB_PREFIX}/w{width}/{object_key}"


def _make_thumbnail(original_bytes: bytes, width: int) -> bytes | None:
    """Decode-resize-encode one thumbnail; ``None`` when the source is not wider.

    ``draft()`` asks the JPEG decoder for the nearest power-of-two-reduced
    raster (1/2 … 1/8) instead of the full one, so a 24MP original costs a
    few MB of RGB rather than ~70MB. That peak, multiplied by the number of
    concurrent requests, is what made this path expensive.
    """
    with PILImage.open(io.BytesIO(original_bytes)) as parsed:
        if parsed.width <= width:
            return None
        # Square request: guarantees the reduced raster still covers the
        # target on whichever axis is short, whatever the aspect ratio.
        parsed.draft("RGB", (width, width))
        ratio = width / parsed.width
        source = parsed if parsed.mode == "RGB" else parsed.convert("RGB")
        resized = source.resize((width, max(1, round(parsed.height * ratio))))
        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=_THUMB_JPEG_QUALITY)
        return buffer.getvalue()


def _stat_or_none(s3: S3Service, key: str):
    try:
        return s3.stat_object(key)
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            return None
        raise HTTPException(status_code=502, detail="Upstream storage error") from exc


def _cache_headers(request: Request, etag: str | None) -> dict[str, str]:
    settings = request.app.state.settings
    headers = {
        "Cache-Control": f"public, max-age={settings.media_cache_max_age}",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if etag:
        headers["ETag"] = etag
    return headers


def _stream_object(request: Request, s3: S3Service, key: str, stat) -> Response:
    """Stream an existing object, honouring If-None-Match."""
    etag = stat.etag
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    return StreamingResponse(
        s3.iter_object(key),
        media_type=stat.content_type or "image/jpeg",
        headers=_cache_headers(request, etag),
    )


@router.get("/media/{object_key:path}")
def get_media(object_key: str, request: Request, w: int | None = None) -> Response:
    """Serve an image (or a cached/lazily-generated thumbnail when ``w`` is set).

    Reserved cache keys under ``thumbs/`` are not directly addressable —
    callers always reference the original key plus ``?w=``.
    """
    s3: S3Service = request.app.state.s3_service
    if object_key.startswith(f"{_THUMB_PREFIX}/"):
        raise HTTPException(status_code=404, detail="Not found")

    if w is None:
        stat = _stat_or_none(s3, object_key)
        if stat is None:
            raise HTTPException(status_code=404, detail="Not found")
        return _stream_object(request, s3, object_key, stat)

    width = snap_width(w)
    thumb_key = _thumb_key(object_key, width)

    cached = _stat_or_none(s3, thumb_key)
    if cached is not None:
        return _stream_object(request, s3, thumb_key, cached)

    original_stat = _stat_or_none(s3, object_key)
    if original_stat is None:
        raise HTTPException(status_code=404, detail="Not found")

    original_bytes = s3.get_object_bytes(object_key)
    # Bounded on purpose: this handler is sync ``def``, so FastAPI runs it in
    # the 40-slot AnyIO threadpool and a gallery page that misses the cache on
    # every tile starts every decode at once. Unbounded, that OOM-killed the
    # API at 1Gi.
    try:
        with request.app.state.thumb_gate:
            thumb_bytes = _make_thumbnail(original_bytes, width)
    except PILImage.UnidentifiedImageError:
        logger.warning("Object %s is not a decodable image; serving original", object_key)
        return _stream_object(request, s3, object_key, original_stat)

    if thumb_bytes is None:
        # Never upscale; serve (and don't cache) the original.
        return _stream_object(request, s3, object_key, original_stat)

    s3.upload_image(thumb_key, thumb_bytes, "image/jpeg")
    return Response(
        content=thumb_bytes,
        media_type="image/jpeg",
        headers=_cache_headers(request, None),
    )
