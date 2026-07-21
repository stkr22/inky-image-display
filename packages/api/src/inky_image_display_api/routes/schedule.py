"""Aggregate-schedule endpoint for the upcoming-refresh dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from inky_image_display_shared.models import Device, Grid
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import ScheduleUpcomingEntry
from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds
from inky_image_display_api.services.queue_service import next_display_at

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("/upcoming", response_model=list[ScheduleUpcomingEntry])
async def upcoming(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ScheduleUpcomingEntry]:
    """Return the next ``limit`` refreshes across devices and grids.

    Grid rows are the next scheduled daily display (grids without an
    enabled schedule have no upcoming refresh of their own). Solo devices
    currently claimed by a grid are excluded — the grid drives them and
    would otherwise appear twice in the queue. Pinned devices are excluded
    too: their scheduled time will not fire, so listing it would promise a
    refresh that never comes. Offline devices are kept so users can see
    they are pending even when the physical panel can't be reached.
    """
    settings = request.app.state.settings
    now = utcnow()

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
        grid_displays = [(g, next_display_at(g, now)) for g in grid_rows.all()]

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
