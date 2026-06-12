"""Read-only proxy over Immich's album/person/tag listings.

Sync-job filters reference Immich entities by UUID; these endpoints let the
UI offer name-based pickers instead of asking users to paste raw IDs. The
proxy is optional — when ``API_IMMICH_BASE_URL`` / ``API_IMMICH_API_KEY``
are unset every endpoint answers 503 and the UI degrades to free-text
inputs. Credentials stay server-side; the browser never talks to Immich.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from inky_image_display_api.schemas import ImmichBrowseItem

if TYPE_CHECKING:
    from inky_image_display_api.config import Settings

router = APIRouter(prefix="/api/immich", tags=["immich"])
logger = logging.getLogger(__name__)

# Immich paginates /people; one page of 1000 covers household libraries.
_PEOPLE_PAGE_SIZE = 1000


async def _fetch_json(settings: Settings, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET a JSON document from Immich using the server-side credentials."""
    if settings.immich_base_url is None or settings.immich_api_key is None:
        raise HTTPException(status_code=503, detail="Immich browsing is not configured on the server.")
    base_url = settings.immich_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"x-api-key": settings.immich_api_key.get_secret_value()},
            timeout=settings.immich_timeout_seconds,
        ) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Immich request %s failed with status %s", path, exc.response.status_code)
        raise HTTPException(status_code=502, detail=f"Immich returned {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        logger.warning("Immich request %s failed: %s", path, exc)
        raise HTTPException(status_code=502, detail="Immich is unreachable") from exc


@router.get("/albums")
async def list_albums(request: Request) -> list[ImmichBrowseItem]:
    """List Immich albums as id/name pairs for the sync-job filter picker."""
    body = await _fetch_json(request.app.state.settings, "/api/albums")
    items = [ImmichBrowseItem(id=a["id"], name=a.get("albumName") or a["id"]) for a in body]
    return sorted(items, key=lambda i: i.name.lower())


@router.get("/people")
async def list_people(request: Request) -> list[ImmichBrowseItem]:
    """List named Immich people (unnamed faces are skipped — they'd render as blanks)."""
    body = await _fetch_json(
        request.app.state.settings,
        "/api/people",
        params={"size": _PEOPLE_PAGE_SIZE, "withHidden": "false"},
    )
    people = body.get("people", []) if isinstance(body, dict) else body
    items = [ImmichBrowseItem(id=p["id"], name=p["name"]) for p in people if p.get("name")]
    return sorted(items, key=lambda i: i.name.lower())


@router.get("/tags")
async def list_tags(request: Request) -> list[ImmichBrowseItem]:
    """List Immich tags; ``value`` carries the full hierarchical path."""
    body = await _fetch_json(request.app.state.settings, "/api/tags")
    items = [ImmichBrowseItem(id=t["id"], name=t.get("value") or t.get("name") or t["id"]) for t in body]
    return sorted(items, key=lambda i: i.name.lower())
