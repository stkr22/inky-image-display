"""Aggregate-schedule endpoint for the upcoming-refresh dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from inky_image_display_shared.models import Device, Grid
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import ScheduleUpcomingEntry
from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("/upcoming", response_model=list[ScheduleUpcomingEntry])
async def upcoming(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ScheduleUpcomingEntry]:
    """Return the next ``limit`` refreshes across devices and grids.

    Solo devices currently claimed by a grid are excluded — the grid
    drives them and would otherwise appear twice in the queue. Pinned
    devices are excluded too: their scheduled time will not fire, so
    listing it would promise a refresh that never comes. Offline devices
    are kept so users can see they are pending even when the physical
    panel can't be reached.
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

        grid_rows = await session.exec(select(Grid).order_by(col(Grid.scheduled_next_at).asc()).limit(limit))
        grids = list(grid_rows.all())

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
        ScheduleUpcomingEntry(
            kind="grid",
            id=g.id,
            name=g.name,
            scheduled_next_at=g.scheduled_next_at,
            refresh_interval_seconds=g.refresh_interval_seconds,
            effective_interval_seconds=g.refresh_interval_seconds or default_seconds,
        )
        for g in grids
    )

    entries.sort(key=lambda e: e.scheduled_next_at)
    return entries[:limit]
