"""Heap profiling endpoints, gated behind ``API_PROFILE_HEAP``.

Under ``/api/`` so the existing policy table already restricts these to the
admin session and the sync token. When profiling is off the routes 404 rather
than 403 — with auth unconfigured (trusted-LAN mode) the env flag is the only
gate, so an absent endpoint is the safer answer.
"""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from inky_image_display_shared import heap_profile

router = APIRouter(prefix="/api/debug", tags=["debug"])


def _require_enabled(request: Request) -> None:
    """404 unless the operator switched profiling on for this process."""
    if not getattr(request.app.state.settings, "profile_heap", False):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/heap")
async def get_heap(
    request: Request,
    top: Annotated[int, Query(gt=0, le=200)] = 25,
    gc_census: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """Return retained allocations since the baseline, largest first."""
    _require_enabled(request)
    return heap_profile.report(top=top, gc_census=gc_census)


@router.post("/heap/baseline")
async def reset_heap_baseline(request: Request) -> dict[str, str]:
    """Re-baseline so the next report covers only what follows this call."""
    _require_enabled(request)
    if not heap_profile.is_active():
        raise HTTPException(status_code=409, detail="Heap profiling is not running")
    heap_profile.capture_baseline()
    return {"status": "baseline reset"}
