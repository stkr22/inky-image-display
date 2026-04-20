"""FastAPI router exposing a read-only proxy over S3-stored image bytes.

The browser side of the UI references images via ``/media/<storage_path>``.
This module owns that endpoint and streams bytes directly from MinIO using
the reader credentials held on ``app.state``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from minio.error import S3Error

if TYPE_CHECKING:
    from collections.abc import Iterator

    from minio import Minio

    from inky_image_display_ui.config import Settings

router = APIRouter(tags=["media"])

_STREAM_CHUNK = 32 * 1024


@router.get("/media/{object_key:path}")
async def get_media(object_key: str, request: Request) -> Response:
    """Stream an S3 object back to the browser.

    Behavior:
        * Stats the object first; a missing object produces a 404 instead of a
          broken stream mid-response.
        * Honors ``If-None-Match`` for conditional GETs.
        * Sets ``Cache-Control`` from :attr:`Settings.media_cache_max_age`.
    """
    client: Minio = request.app.state.minio_client
    settings: Settings = request.app.state.settings

    try:
        stat = client.stat_object(settings.s3_bucket, object_key)
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Not found") from exc
        raise HTTPException(status_code=502, detail="Upstream storage error") from exc

    etag = stat.etag
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    http_response = client.get_object(settings.s3_bucket, object_key)

    def iter_chunks() -> Iterator[bytes]:
        try:
            yield from http_response.stream(_STREAM_CHUNK)
        finally:
            http_response.close()
            http_response.release_conn()

    headers: dict[str, str] = {
        "Cache-Control": f"public, max-age={settings.media_cache_max_age}",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if etag:
        headers["ETag"] = etag

    return StreamingResponse(
        iter_chunks(),
        media_type=stat.content_type or "image/jpeg",
        headers=headers,
    )
