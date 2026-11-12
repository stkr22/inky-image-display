"""Grid display orchestration.

A grid is a virtual canvas in physical centimetres on which devices are
placed. When a grid displays an image, the source image is cover-fitted to
the canvas and each placed device receives a pre-cropped slice at its
native pixel resolution. Slices are cached under
``grids/{grid_id}/{image_id}/`` and pushed to devices by the queue
(``queue_service``) via the normal MQTT ``DisplayCommand`` flow.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import astuple, dataclass
from datetime import timedelta
from io import BytesIO
from typing import TYPE_CHECKING

import pillow_heif
from fastapi import HTTPException
from inky_image_display_shared.models import Device, DeviceProfile, Grid, GridDevice, Image
from inky_image_display_shared.time import utcnow
from PIL import Image as PILImage
from PIL import ImageOps
from PIL.Image import Resampling
from sqlmodel import col, select

from inky_image_display_api.services.image_deletion import grid_crop_dir
from inky_image_display_api.services.s3_service import stat_or_none

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from inky_image_display_api.services.s3_service import S3Service

pillow_heif.register_heif_opener()

logger = logging.getLogger(__name__)


def hold_horizon(grid: Grid, now: datetime) -> datetime:
    """When the current display ends: duration-based, or manual release only.

    The no-duration fallback is ~10 years out — far enough that the
    hold-expiry tick never fires on its own.
    """
    duration = grid.display_duration_seconds
    return now + timedelta(seconds=duration) if duration else now + timedelta(days=3650)


def oriented_physical_dims(profile: DeviceProfile, orientation: str) -> tuple[float, float]:
    """Return (width_cm, height_cm) for the device as mounted.

    Profile dims are stored landscape-native; portrait-mounted devices
    swap them.
    """
    if orientation == "portrait":
        return profile.physical_height_cm, profile.physical_width_cm
    return profile.physical_width_cm, profile.physical_height_cm


def oriented_pixel_dims(profile: DeviceProfile, orientation: str) -> tuple[int, int]:
    """Return (width_px, height_px) for the device as mounted."""
    if orientation == "portrait":
        return profile.height, profile.width
    return profile.width, profile.height


@dataclass(frozen=True)
class SlotTarget:
    """A resolved grid slot: its device and oriented panel dimensions."""

    device: Device
    width: int
    height: int
    is_portrait: bool


async def placement_targets(session: AsyncSession, grid_id: UUID) -> list[tuple[GridDevice, SlotTarget]]:
    """Every placement with its device and oriented panel size, in slot order.

    One joined query: the display paths run this per push, and a query per
    placement for device and profile added up on larger walls.
    """
    result = await session.exec(
        select(GridDevice, Device, DeviceProfile)
        .join(Device, col(Device.id) == col(GridDevice.device_id))
        .join(DeviceProfile, col(DeviceProfile.id) == col(Device.device_profile_id))
        .where(col(GridDevice.grid_id) == grid_id)
        .order_by(col(GridDevice.row), col(GridDevice.col))
    )
    rows: list[tuple[GridDevice, SlotTarget]] = []
    for placement, device, profile in result.all():
        width, height = oriented_pixel_dims(profile, device.display_orientation)
        target = SlotTarget(
            device=device, width=width, height=height, is_portrait=device.display_orientation == "portrait"
        )
        rows.append((placement, target))
    return rows


async def resolve_slot_targets(session: AsyncSession, grid_id: UUID) -> dict[tuple[int, int], SlotTarget]:
    """Map each grid slot (row, col) to its device and panel dimensions."""
    return {(placement.row, placement.col): target for placement, target in await placement_targets(session, grid_id)}


async def list_grid_devices(session: AsyncSession, grid_id: UUID) -> list[GridDevice]:
    """Return all placements for a grid, in slot order (top-left first)."""
    result = await session.exec(
        select(GridDevice).where(col(GridDevice.grid_id) == grid_id).order_by(col(GridDevice.row), col(GridDevice.col))
    )
    return list(result.all())


async def apply_layout(session: AsyncSession, grid: Grid, device_rows: list[list[UUID]]) -> None:
    """Replace a grid's placements with a computed tile layout.

    ``device_rows`` is the visual arrangement: rows top-down, devices
    left-to-right. Every cm value is derived from the device profiles'
    physical dimensions, assuming panels sit flush against each other
    (no white space). Mixed sizes are centred: a shorter panel is centred
    vertically within its row, a narrower row centred horizontally on the
    canvas — the symmetric arrangement someone would hang on a wall.

    Does not commit; the caller owns the transaction.
    """
    flat = [device_id for row in device_rows for device_id in row]
    if not flat:
        raise HTTPException(status_code=400, detail="A grid layout needs at least one device")
    if len(set(flat)) != len(flat):
        raise HTTPException(status_code=400, detail="A device can appear only once in the layout")

    # Batched: one query for the devices with their profiles, one for
    # conflicting placements, instead of several per device.
    found = await session.exec(
        select(Device, DeviceProfile)
        .join(DeviceProfile, col(DeviceProfile.id) == col(Device.device_profile_id))
        .where(col(Device.id).in_(flat))
    )
    by_id = {device.id: (device, profile) for device, profile in found.all()}
    if len(by_id) != len(flat):
        raise HTTPException(status_code=404, detail="Device not found")
    elsewhere = await session.exec(
        select(GridDevice.device_id).where(col(GridDevice.device_id).in_(flat), col(GridDevice.grid_id) != grid.id)
    )
    taken = elsewhere.first()
    if taken is not None:
        raise HTTPException(
            status_code=409, detail=f"Device {by_id[taken][0].device_id} is already part of another grid"
        )

    sized_rows: list[list[tuple[Device, float, float]]] = []
    for row in device_rows:
        sized_row: list[tuple[Device, float, float]] = []
        for device_id in row:
            device, profile = by_id[device_id]
            width_cm, height_cm = oriented_physical_dims(profile, device.display_orientation)
            sized_row.append((device, width_cm, height_cm))
        sized_rows.append(sized_row)

    row_widths = [sum(w for _, w, _ in row) for row in sized_rows]
    row_heights = [max(h for _, _, h in row) for row in sized_rows]
    canvas_width = max(row_widths)
    canvas_height = sum(row_heights)

    # Devices dropped from the layout stop being driven by this grid.
    kept_ids = set(flat)
    placements = await list_grid_devices(session, grid.id)
    dropped_ids = [p.device_id for p in placements if p.device_id not in kept_ids]
    if dropped_ids:
        dropped = await session.exec(
            select(Device).where(col(Device.id).in_(dropped_ids), col(Device.claimed_by_grid_id) == grid.id)
        )
        for device in dropped.all():
            device.claimed_by_grid_id = None
            session.add(device)
    for placement in placements:
        await session.delete(placement)
    await session.flush()

    y_offset = 0.0
    for row_index, sized_row in enumerate(sized_rows):
        x_offset = (canvas_width - row_widths[row_index]) / 2
        for col_index, (device, width_cm, height_cm) in enumerate(sized_row):
            session.add(
                GridDevice(
                    grid_id=grid.id,
                    device_id=device.id,
                    row=row_index,
                    col=col_index,
                    top_left_x_cm=x_offset,
                    top_left_y_cm=y_offset + (row_heights[row_index] - height_cm) / 2,
                    width_cm=width_cm,
                    height_cm=height_cm,
                )
            )
            x_offset += width_cm
        y_offset += row_heights[row_index]

    grid.width_cm = canvas_width
    grid.height_cm = canvas_height
    grid.updated_at = utcnow()
    session.add(grid)


async def get_grid_or_404(session: AsyncSession, grid_id: UUID) -> Grid:
    """Fetch a grid by id, raising 404 if missing."""
    result = await session.exec(select(Grid).where(col(Grid.id) == grid_id))
    grid = result.first()
    if grid is None:
        raise HTTPException(status_code=404, detail="Grid not found")
    return grid


@dataclass(frozen=True)
class CropSpec:
    """Plain-value crop geometry, safe to hand to a worker thread.

    ORM instances must not cross into the thread (an expired attribute
    would try to lazy-load there), so the render step gets copies.
    """

    canvas_width_cm: float
    canvas_height_cm: float
    left_cm: float
    top_cm: float
    width_cm: float
    height_cm: float
    target_size: tuple[int, int]

    @classmethod
    def of(cls, grid: Grid, placement: GridDevice, target_size: tuple[int, int]) -> CropSpec:
        """Snapshot the geometry of one placement on ``grid``."""
        return cls(
            canvas_width_cm=grid.width_cm,
            canvas_height_cm=grid.height_cm,
            left_cm=placement.top_left_x_cm,
            top_cm=placement.top_left_y_cm,
            width_cm=placement.width_cm,
            height_cm=placement.height_cm,
            target_size=target_size,
        )


def decode_rgb(image_data: bytes) -> PILImage.Image:
    """Decode, apply EXIF rotation and normalise to RGB."""
    with PILImage.open(BytesIO(image_data)) as original:
        oriented = ImageOps.exif_transpose(original) or original
        return oriented.convert("RGB") if oriented.mode != "RGB" else oriented.copy()


def crop_decoded(rgb: PILImage.Image, spec: CropSpec, *, quality: int = 85) -> bytes:
    """Crop and resize an already-decoded source to one device's slice.

    The source image is cover-fitted to the canvas (so it fully covers
    every cm of the grid, cropping overflow on one axis). The device's
    cm-rectangle then maps directly onto the projected region.
    """
    img_w, img_h = rgb.size
    canvas_aspect = spec.canvas_width_cm / spec.canvas_height_cm
    image_aspect = img_w / img_h

    # Cover-fit: pick the source-image rect that maps to the entire canvas
    # while preserving aspect ratio. The other axis is centre-cropped.
    if image_aspect > canvas_aspect:
        used_h = img_h
        used_w = img_h * canvas_aspect
        used_left = (img_w - used_w) / 2
        used_top = 0.0
    else:
        used_w = img_w
        used_h = img_w / canvas_aspect
        used_left = 0.0
        used_top = (img_h - used_h) / 2

    px_per_cm_x = used_w / spec.canvas_width_cm
    px_per_cm_y = used_h / spec.canvas_height_cm

    crop_left = used_left + spec.left_cm * px_per_cm_x
    crop_top = used_top + spec.top_cm * px_per_cm_y
    crop_right = crop_left + spec.width_cm * px_per_cm_x
    crop_bottom = crop_top + spec.height_cm * px_per_cm_y

    cropped = rgb.crop((int(crop_left), int(crop_top), int(crop_right), int(crop_bottom)))
    resized = cropped.resize(spec.target_size, resample=Resampling.LANCZOS)

    out = BytesIO()
    resized.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def compute_crop_for_device(
    image_data: bytes,
    grid: Grid,
    placement: GridDevice,
    target_pixel_size: tuple[int, int],
    *,
    quality: int = 85,
) -> bytes:
    """Decode ``image_data`` and crop one device's slice (single-slice form)."""
    return crop_decoded(decode_rgb(image_data), CropSpec.of(grid, placement, target_pixel_size), quality=quality)


def grid_crop_storage_path(grid_id: UUID, image_id: UUID, device_id: UUID, spec: CropSpec) -> str:
    """Build the S3 object key for a grid crop.

    The geometry digest is part of the name so a cached crop is reused only
    while it is still correct: re-arranging the layout or re-mounting a
    panel in another orientation yields a new key instead of a stale slice.
    """
    digest = hashlib.sha256(repr(astuple(spec)).encode()).hexdigest()[:12]
    return f"{grid_crop_dir(grid_id, image_id)}{device_id}-{digest}.jpg"


def _render_missing_crops(s3: S3Service, source_key: str, crops: list[tuple[str, CropSpec]]) -> None:
    """Render and upload the crops not already in the bucket.

    Runs in a worker thread: the MinIO SDK and Pillow both block. The
    source is decoded once for all slices, and not at all when every crop
    is cached — a replayed queue entry costs a few stats, not a decode.
    """
    missing = [(key, spec) for key, spec in crops if stat_or_none(s3, key) is None]
    if not missing:
        return
    source = decode_rgb(s3.get_object_bytes(source_key))
    for key, spec in missing:
        s3.upload_image(key, crop_decoded(source, spec), "image/jpeg")


async def render_and_upload(
    grid: Grid,
    image: Image,
    rows: list[tuple[GridDevice, SlotTarget]],
    s3: S3Service,
    gate: asyncio.Semaphore,
) -> dict[UUID, str]:
    """Ensure every placement's crop exists in S3; return device id -> key.

    The process gate bounds concurrent full-size decodes across the API
    (uploads, GenAI, previews) so a burst can't exhaust memory.
    """
    if not rows:
        raise HTTPException(status_code=400, detail="Grid has no devices placed")
    crops = {
        target.device.id: (
            grid_crop_storage_path(grid.id, image.id, target.device.id, spec),
            spec,
        )
        for placement, target in rows
        for spec in [CropSpec.of(grid, placement, (target.width, target.height))]
    }
    async with gate:
        await asyncio.to_thread(_render_missing_crops, s3, image.storage_path, list(crops.values()))
    return {device_id: key for device_id, (key, _spec) in crops.items()}
