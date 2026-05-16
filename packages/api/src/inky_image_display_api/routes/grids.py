"""REST endpoints for grid display management."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from inky_image_display_shared.models import Device, Grid, GridDevice, Image
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    GridCreate,
    GridDeviceAdd,
    GridDeviceResponse,
    GridDeviceUpdate,
    GridDisplayRequest,
    GridResponse,
    GridUpdate,
)
from inky_image_display_api.services import grid_service

router = APIRouter(prefix="/api/grids", tags=["grids"])
logger = logging.getLogger(__name__)


def _to_device_response(placement: GridDevice, grid_height_cm: float) -> GridDeviceResponse:
    # Convert stored top-left (Y-down) back to user-facing bottom-left (Y-up).
    return GridDeviceResponse(
        grid_id=placement.grid_id,
        device_id=placement.device_id,
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
    """Create a new grid canvas."""
    grid = Grid(name=body.name, width_cm=body.width_cm, height_cm=body.height_cm)
    async with AsyncSession(request.app.state.engine) as session:
        session.add(grid)
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
    """Rename or resize a grid.

    Resizing re-validates every member device rect against the new canvas.
    """
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        if body.name is not None:
            grid.name = body.name
        if body.width_cm is not None:
            grid.width_cm = body.width_cm
        if body.height_cm is not None:
            grid.height_cm = body.height_cm

        if body.width_cm is not None or body.height_cm is not None:
            placements = await grid_service.list_grid_devices(session, grid.id)
            for p in placements:
                rect = grid_service.DeviceRect(
                    top_left_x_cm=p.top_left_x_cm,
                    top_left_y_cm=p.top_left_y_cm,
                    width_cm=p.width_cm,
                    height_cm=p.height_cm,
                )
                grid_service.validate_rect_in_canvas(grid, rect)

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
        await grid_service.release_grid(session, grid)
        targeted = await session.exec(select(Image).where(col(Image.target_grid_id) == grid.id))
        for image in targeted.all():
            image.target_grid_id = None
            session.add(image)
        await session.delete(grid)
        await session.commit()


@router.post("/{grid_id}/devices", status_code=201)
async def add_device_to_grid(request: Request, grid_id: UUID, body: GridDeviceAdd) -> GridDeviceResponse:
    """Place a device on the grid (or 400 if rect overflows)."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        device = await grid_service.get_device_or_404(session, body.device_id)
        profile = await grid_service.get_profile(session, device.device_profile_id)
        existing = await session.exec(
            select(GridDevice).where(
                col(GridDevice.grid_id) == grid_id,
                col(GridDevice.device_id) == body.device_id,
            )
        )
        if existing.first() is not None:
            raise HTTPException(status_code=409, detail="Device is already placed on this grid")

        rect = grid_service.derive_rect(
            grid,
            profile,
            device.display_orientation,
            bottom_left_x_cm=body.bottom_left_x_cm,
            bottom_left_y_cm=body.bottom_left_y_cm,
        )
        _warn_on_overlap(grid_id, rect, await grid_service.list_grid_devices(session, grid_id))

        placement = GridDevice(
            grid_id=grid.id,
            device_id=device.id,
            top_left_x_cm=rect.top_left_x_cm,
            top_left_y_cm=rect.top_left_y_cm,
            width_cm=rect.width_cm,
            height_cm=rect.height_cm,
        )
        # Capture grid height before commit — the ORM expires `grid` on commit.
        grid_height_cm = grid.height_cm
        session.add(placement)
        await session.commit()
        await session.refresh(placement)
        return _to_device_response(placement, grid_height_cm)


@router.put("/{grid_id}/devices/{device_id}")
async def update_device_placement(
    request: Request,
    grid_id: UUID,
    device_id: UUID,
    body: GridDeviceUpdate,
) -> GridDeviceResponse:
    """Move a placed device to a new bottom-left corner."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        device = await grid_service.get_device_or_404(session, device_id)
        profile = await grid_service.get_profile(session, device.device_profile_id)
        placement_result = await session.exec(
            select(GridDevice).where(
                col(GridDevice.grid_id) == grid_id,
                col(GridDevice.device_id) == device_id,
            )
        )
        placement = placement_result.first()
        if placement is None:
            raise HTTPException(status_code=404, detail="Device is not placed on this grid")

        rect = grid_service.derive_rect(
            grid,
            profile,
            device.display_orientation,
            bottom_left_x_cm=body.bottom_left_x_cm,
            bottom_left_y_cm=body.bottom_left_y_cm,
        )
        placement.top_left_x_cm = rect.top_left_x_cm
        placement.top_left_y_cm = rect.top_left_y_cm
        placement.width_cm = rect.width_cm
        placement.height_cm = rect.height_cm
        grid_height_cm = grid.height_cm
        session.add(placement)
        await session.commit()
        await session.refresh(placement)
        return _to_device_response(placement, grid_height_cm)


@router.delete("/{grid_id}/devices/{device_id}", status_code=204)
async def remove_device_from_grid(request: Request, grid_id: UUID, device_id: UUID) -> None:
    """Remove a device from a grid; releases its claim if held by this grid."""
    async with AsyncSession(request.app.state.engine) as session:
        placement_result = await session.exec(
            select(GridDevice).where(
                col(GridDevice.grid_id) == grid_id,
                col(GridDevice.device_id) == device_id,
            )
        )
        placement = placement_result.first()
        if placement is None:
            raise HTTPException(status_code=404, detail="Device is not placed on this grid")

        device_result = await session.exec(select(Device).where(col(Device.id) == device_id))
        device = device_result.first()
        if device is not None and device.claimed_by_grid_id == grid_id:
            device.claimed_by_grid_id = None
            session.add(device)

        await session.delete(placement)
        await session.commit()


@router.post("/{grid_id}/display")
async def display_image_on_grid(
    request: Request,
    grid_id: UUID,
    body: GridDisplayRequest,
) -> dict[str, str]:
    """Render slices for ``body.image_id`` and push them to every member device."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        image_result = await session.exec(select(Image).where(col(Image.id) == body.image_id))
        image = image_result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")
        if image.target_grid_id is not None and image.target_grid_id != grid.id:
            raise HTTPException(status_code=400, detail="Image targets a different grid")

        crop_paths = await grid_service.render_and_upload(session, grid, image, request.app.state.s3_service)
        await grid_service.claim_devices_and_push(
            session,
            grid,
            image,
            crop_paths,
            request.app.state.mqtt,
        )
        return {"status": "ok"}


@router.post("/{grid_id}/next")
async def advance_grid_rotation(request: Request, grid_id: UUID) -> dict[str, str]:
    """Pick the next image from the grid's pool and push it."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        image = await grid_service.get_next_grid_image(session, grid)
        if image is None:
            raise HTTPException(status_code=404, detail="No images assigned to this grid")
        crop_paths = await grid_service.render_and_upload(session, grid, image, request.app.state.s3_service)
        await grid_service.claim_devices_and_push(
            session,
            grid,
            image,
            crop_paths,
            request.app.state.mqtt,
        )
        return {"status": "ok", "image_id": str(image.id)}


@router.post("/{grid_id}/release")
async def release_grid_claims(request: Request, grid_id: UUID) -> dict[str, str]:
    """Release every claim this grid holds; devices return to solo rotation."""
    async with AsyncSession(request.app.state.engine) as session:
        grid = await grid_service.get_grid_or_404(session, grid_id)
        await grid_service.release_grid(session, grid)
        return {"status": "ok"}


def _warn_on_overlap(grid_id: UUID, new_rect: grid_service.DeviceRect, existing: list[GridDevice]) -> None:
    for other in existing:
        if _rects_overlap(new_rect, other):
            logger.warning(
                "Grid %s placement overlaps existing device %s — allowing but flagging",
                grid_id,
                other.device_id,
            )


def _rects_overlap(a: grid_service.DeviceRect, b: GridDevice) -> bool:
    if a.top_left_x_cm + a.width_cm <= b.top_left_x_cm:
        return False
    if b.top_left_x_cm + b.width_cm <= a.top_left_x_cm:
        return False
    if a.top_left_y_cm + a.height_cm <= b.top_left_y_cm:
        return False
    return not b.top_left_y_cm + b.height_cm <= a.top_left_y_cm
