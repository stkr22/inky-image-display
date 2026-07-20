"""REST endpoints for grid display management.

Grid layouts are tile arrangements: the client sends rows of device ids
and every cm value (canvas size, placement rects) is computed from the
device profiles' physical dimensions — no manual coordinates.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from inky_image_display_shared.models import Grid, GridDevice, Image, ImageGroup
from inky_image_display_shared.schemas.responses import (
    GridContentStatus,
    GridQueueEntry,
    GridSlotStatus,
    GroupDisplayResult,
)
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    GridCreate,
    GridDeviceResponse,
    GridDisplayGroupRequest,
    GridDisplayRequest,
    GridQueueReorder,
    GridResponse,
    GridUpdate,
)
from inky_image_display_api.services import grid_service, queue_service
from inky_image_display_api.services.queue_service import QueueError

router = APIRouter(prefix="/api/grids", tags=["grids"])
logger = logging.getLogger(__name__)


def _to_device_response(placement: GridDevice, grid_height_cm: float) -> GridDeviceResponse:
    # Convert stored top-left (Y-down) back to user-facing bottom-left (Y-up).
    return GridDeviceResponse(
        grid_id=placement.grid_id,
        device_id=placement.device_id,
        row=placement.row,
        col=placement.col,
        bottom_left_x_cm=placement.top_left_x_cm,
        bottom_left_y_cm=grid_height_cm - placement.top_left_y_cm - placement.height_cm,
        width_cm=placement.width_cm,
        height_cm=placement.height_cm,
    )


async def _build_response(session: AsyncSession, grid: Grid, *, include_devices: bool) -> GridResponse:
    response = GridResponse.model_validate(grid)
    if include_devices:
        placements = await grid_service.list_grid_devices(session, grid.id)
        response.devices = [_to_device_response(p, grid.height_cm) for p in placements]
    return response


@router.get("")
async def list_grids(
    request: Request,
    include_devices: Annotated[bool, Query()] = False,
) -> list[GridResponse]:
    """List grids; pass ``include_devices=true`` to embed placements."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Grid))
        grids = list(result.all())
        return [await _build_response(session, g, include_devices=include_devices) for g in grids]


@router.post("", status_code=201)
async def create_grid(request: Request, body: GridCreate) -> GridResponse:
    """Create a grid from a tile layout."""
    grid = Grid(name=body.name, width_cm=0.0, height_cm=0.0, refresh_interval_seconds=body.refresh_interval_seconds)
    async with AsyncSession(request.app.state.engine) as session:
        session.add(grid)
        await session.flush()
        await grid_service.apply_layout(session, grid, body.rows)
        await session.commit()
        await session.refresh(grid)
        return await _build_response(session, grid, include_devices=True)


@router.get("/{grid_id}")
async def get_grid(request: Request, grid_id: UUID) -> GridResponse:
    """Fetch a single grid by id (with placements)."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        return await _build_response(session, grid, include_devices=True)


@router.put("/{grid_id}")
async def update_grid(request: Request, grid_id: UUID, body: GridUpdate) -> GridResponse:
    """Rename a grid, change its cadence or display schedule, or replace its layout."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        if body.name is not None:
            grid.name = body.name
        if body.clear_refresh_interval:
            grid.refresh_interval_seconds = None
        elif body.refresh_interval_seconds is not None:
            grid.refresh_interval_seconds = body.refresh_interval_seconds
        for field_name in ("display_schedule_enabled", "display_time", "display_weekday_mask", "display_timezone"):
            value = getattr(body, field_name)
            if value is not None:
                setattr(grid, field_name, value)
        if body.clear_display_duration:
            grid.display_duration_seconds = None
        elif body.display_duration_seconds is not None:
            grid.display_duration_seconds = body.display_duration_seconds
        if body.rows is not None:
            await grid_service.apply_layout(session, grid, body.rows)

        session.add(grid)
        await session.commit()
        await session.refresh(grid)
        return await _build_response(session, grid, include_devices=True)


@router.delete("/{grid_id}", status_code=204)
async def delete_grid(request: Request, grid_id: UUID) -> None:
    """Delete a grid; cascades to ``grid_devices`` and releases claims."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        # Clear claims and decouple images from the grid pool before deletion.
        # `release_grid` commits and expires `grid`; refresh so later attribute
        # access and `session.delete(grid)` don't trigger an async lazy-load.
        await grid_service.release_grid(session, grid)
        await session.refresh(grid)
        targeted = await session.exec(select(Image).where(col(Image.target_grid_id) == grid_id))
        for image in targeted.all():
            image.target_grid_id = None
            session.add(image)
        await session.delete(grid)
        await session.commit()


@router.post("/{grid_id}/display")
async def display_image_on_grid(
    request: Request,
    grid_id: UUID,
    body: GridDisplayRequest,
) -> dict[str, str]:
    """Render slices for ``body.image_id`` and push them to every member device.

    A manual push is an operator override: any held group is dropped and
    the queue resumes from here on the next refresh.
    """
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        image_result = await session.exec(select(Image).where(col(Image.id) == body.image_id))
        image = image_result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")
        if image.target_grid_id is not None and image.target_grid_id != grid.id:
            raise HTTPException(status_code=400, detail="Image targets a different grid")

        grid.current_group_id = None
        grid.current_frame = 0
        grid.hold_until = None
        crop_paths = await grid_service.render_and_upload(session, grid, image, request.app.state.s3_service)
        await grid_service.claim_devices_and_push(
            session,
            grid,
            image,
            crop_paths,
            request.app.state.mqtt,
            request.app.state.settings,
        )
        return {"status": "ok"}


@router.post("/{grid_id}/next")
async def advance_grid_rotation(request: Request, grid_id: UUID) -> dict[str, str]:
    """Advance the queue one step now (skips the rest of a running group)."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        await queue_service.advance_grid(request.app, session, grid, force_next=True)
        return {"status": "ok"}


@router.post("/{grid_id}/release")
async def release_grid_content(request: Request, grid_id: UUID) -> dict[str, str]:
    """End any held group and resume the queue immediately.

    The panels update right away; the next refresh is jittered so grids
    released together don't flash in lockstep. With an empty queue the
    member devices return to (jittered) solo rotation instead.
    """
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        await queue_service.release_queue(request.app, session, grid)
        return {"status": "ok"}


@router.post("/{grid_id}/display-group")
async def display_group_on_grid(request: Request, grid_id: UUID, body: GridDisplayGroupRequest) -> GroupDisplayResult:
    """Show a group on this grid now, holding it per the grid's duration."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        group = await session.get(ImageGroup, body.group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Image group not found")
        try:
            return await queue_service.start_group(request.app, session, grid, group)
        except QueueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{grid_id}/queue")
async def get_grid_queue(request: Request, grid_id: UUID) -> list[GridQueueEntry]:
    """Return the grid's content queue in predicted playback order."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        entries: list[GridQueueEntry] = []
        for kind, obj in await queue_service.queue_entries(session, grid.id):
            if isinstance(obj, ImageGroup):
                images = await queue_service.group_images(session, obj.id)
                entries.append(
                    GridQueueEntry(
                        kind=kind,
                        id=obj.id,
                        name=obj.name,
                        last_displayed_at=obj.last_displayed_at,
                        frame_count=queue_service.frame_count(images),
                        storage_path=images[0].storage_path if images else None,
                        is_current=grid.current_group_id == obj.id,
                    )
                )
            else:
                entries.append(
                    GridQueueEntry(
                        kind=kind,
                        id=obj.id,
                        name=obj.title,
                        last_displayed_at=obj.last_displayed_at,
                        frame_count=1,
                        storage_path=obj.storage_path,
                        is_current=grid.current_group_id is None and grid.current_image_id == obj.id,
                    )
                )
        return entries


@router.put("/{grid_id}/queue")
async def reorder_grid_queue(request: Request, grid_id: UUID, body: GridQueueReorder) -> list[GridQueueEntry]:
    """Persist the operator's queue order.

    Positions are assigned across groups and loose images in one shared
    sequence, so both kinds interleave. Entries not listed keep their old
    position (they sort after the listed ones only by chance — send the
    full queue).
    """
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        for position, entry in enumerate(body.entries):
            if entry.kind == "group":
                group = await session.get(ImageGroup, entry.id)
                if group is not None and group.target_grid_id == grid.id:
                    group.queue_position = position
                    session.add(group)
            else:
                image = await session.get(Image, entry.id)
                if image is not None and image.target_grid_id == grid.id and image.group_id is None:
                    image.queue_position = position
                    session.add(image)
        await session.commit()
    return await get_grid_queue(request, grid_id)


@router.get("/{grid_id}/display-status")
async def get_display_status(request: Request, grid_id: UUID) -> GridContentStatus:
    """Report what the grid's queue is currently playing, per panel."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        group = None
        images: list[Image] = []
        if grid.current_group_id is not None:
            group = await session.get(ImageGroup, grid.current_group_id)
            if group is not None:
                images = await queue_service.group_images(session, group.id)
        slotted, _canvas = queue_service.split_frames(images)
        slot_statuses: list[GridSlotStatus] = []
        targets = await grid_service.resolve_slot_targets(session, grid.id)
        for key, target in sorted(targets.items()):
            sequence = slotted.get(key)
            current_title = None
            if sequence:
                current_title = sequence[grid.current_frame % len(sequence)].title
            elif target.device.current_image_id is not None:
                image = await session.get(Image, target.device.current_image_id)
                current_title = image.title if image is not None else None
            slot_statuses.append(
                GridSlotStatus(
                    row=key[0],
                    col=key[1],
                    device_id=target.device.device_id,
                    is_online=target.device.is_online,
                    current_title=current_title,
                )
            )
        return GridContentStatus(
            group_id=grid.current_group_id,
            group_name=group.name if group is not None else None,
            frame=grid.current_frame,
            frame_count=queue_service.frame_count(images),
            hold_until=grid.hold_until,
            displayed_since=grid.displayed_since,
            slots=slot_statuses,
        )
