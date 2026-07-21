"""Aggregate-schedule endpoint for the upcoming-refresh dashboard."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic needs the runtime type
from typing import Annotated

from fastapi import APIRouter, Query, Request
from inky_image_display_shared.models import Device, Grid
from inky_image_display_shared.schemas.responses import UtcDatetime  # noqa: TC002 — pydantic resolves at runtime
from inky_image_display_shared.time import utcnow
from pydantic import BaseModel
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import CronExpression, ScheduleTimezone, ScheduleUpcomingEntry
from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds
from inky_image_display_api.services.sync_job_scheduling import next_cron_run

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class CronPreviewRequest(BaseModel):
    """Body for ``POST /api/schedule/cron-preview``.

    Validation errors (bad cron, unknown timezone) surface as 422 with
    the validator's message, which the job forms show inline.
    """

    cron: CronExpression
    timezone: ScheduleTimezone = "UTC"


class CronPreviewResponse(BaseModel):
    """The next few occurrences of a cron expression, as aware UTC times."""

    next_runs: list[UtcDatetime]


@router.get("/worker-status")
async def worker_status(request: Request) -> dict[str, bool]:
    """Report sync-worker liveness (retained MQTT status) for the Jobs page."""
    return {"online": request.app.state.mqtt.worker_online}


@router.post("/cron-preview", response_model=CronPreviewResponse)
async def cron_preview(body: CronPreviewRequest) -> CronPreviewResponse:
    """Preview a schedule before saving: its next three occurrences."""
    runs: list[datetime] = []
    cursor = utcnow()
    for _ in range(3):
        cursor = next_cron_run(body.cron, body.timezone, cursor)
        runs.append(cursor)
    return CronPreviewResponse(next_runs=runs)


@router.get("/upcoming", response_model=list[ScheduleUpcomingEntry])
async def upcoming(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ScheduleUpcomingEntry]:
    """Return the next ``limit`` refreshes across devices and grids.

    Grid rows are the next scheduled display (grids without an enabled
    schedule have no upcoming refresh of their own). Solo devices
    currently claimed by a grid are excluded — the grid drives them and
    would otherwise appear twice in the queue. Pinned devices are excluded
    too: their scheduled time will not fire, so listing it would promise a
    refresh that never comes. Offline devices are kept so users can see
    they are pending even when the physical panel can't be reached.
    """
    settings = request.app.state.settings

    async with AsyncSession(request.app.state.engine) as session:
        default_seconds = await get_default_refresh_seconds(session, settings)
        device_rows = await session.exec(
            select(Device)
            .where(
                col(Device.claimed_by_grid_id).is_(None),
                col(Device.is_pinned).is_(False),
            )
            .order_by(col(Device.scheduled_next_at).asc())
            .limit(limit)
        )
        devices = list(device_rows.all())

        grid_rows = await session.exec(select(Grid).where(col(Grid.display_schedule_enabled).is_(True)))
        # display_next_at is the lease the queue tick fires on — reading it
        # directly keeps this endpoint and the scheduler in agreement.
        grid_displays = [(g, g.display_next_at) for g in grid_rows.all()]

    entries: list[ScheduleUpcomingEntry] = [
        ScheduleUpcomingEntry(
            kind="device",
            id=d.id,
            name=d.device_id,
            scheduled_next_at=d.scheduled_next_at,
            refresh_interval_seconds=d.refresh_interval_seconds,
            effective_interval_seconds=d.refresh_interval_seconds or default_seconds,
        )
        for d in devices
    ]
    entries.extend(
        ScheduleUpcomingEntry(kind="grid", id=g.id, name=g.name, scheduled_next_at=display_at)
        for g, display_at in grid_displays
        if display_at is not None
    )

    entries.sort(key=lambda e: e.scheduled_next_at)
    return entries[:limit]
