"""Grid display orchestration.

A grid is a virtual canvas in physical centimetres on which devices are
placed. When a grid displays an image, the source image is cover-fitted to
the canvas and each placed device receives a pre-cropped slice at its
native pixel resolution. Slices are uploaded under
``grids/{grid_id}/{image_id}/{device_id}.jpg`` and pushed to devices via
the normal MQTT ``DisplayCommand`` flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

import pillow_heif
from fastapi import HTTPException
from inky_image_display_shared.models import Device, DeviceProfile, Grid, GridDevice, Image
from inky_image_display_shared.schemas import DisplayCommand
from inky_image_display_shared.time import utcnow
from PIL import Image as PILImage
from PIL import ImageOps
from PIL.Image import Resampling
from sqlmodel import col, select

from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds
from inky_image_display_api.services.image_service import next_refresh_at

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from inky_image_display_api.config import Settings
    from inky_image_display_api.mqtt import MQTTService
    from inky_image_display_api.services.s3_service import S3Service

pillow_heif.register_heif_opener()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceRect:
    """A device's stored placement.

    Internal coordinates are top-left origin because PIL crop and CSS
    positioning both want top-left. Callers translate to/from the
    user-facing bottom-left origin at the API boundary.
    """

    top_left_x_cm: float
    top_left_y_cm: float
    width_cm: float
    height_cm: float

    def bottom_left_x_cm(self) -> float:
        """Bottom-left x in user-facing (Y-up) coordinates."""
        return self.top_left_x_cm

    def bottom_left_y_cm(self, grid_height_cm: float) -> float:
        """Bottom-left y in user-facing (Y-up) coordinates."""
        return grid_height_cm - self.top_left_y_cm - self.height_cm


class GridValidationError(HTTPException):
    """Raised when grid placement or claim invariants are violated."""

    def __init__(self, status_code: int, detail: str) -> None:
        """Initialise an HTTPException with a custom status code."""
        super().__init__(status_code=status_code, detail=detail)


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


def derive_rect(
    grid: Grid,
    profile: DeviceProfile,
    orientation: str,
    *,
    bottom_left_x_cm: float,
    bottom_left_y_cm: float,
) -> DeviceRect:
    """Resolve a device placement from a bottom-left (Y-up) corner.

    The persisted rectangle has dimensions snapshotted from the profile so
    later profile-spec corrections don't silently move existing placements.
    Validates that the rect lies fully within the canvas.
    """
    width_cm, height_cm = oriented_physical_dims(profile, orientation)

    # Bottom-left (Y-up, user-facing) → top-left (Y-down, internal).
    top_left_x = bottom_left_x_cm
    top_left_y = grid.height_cm - bottom_left_y_cm - height_cm

    rect = DeviceRect(
        top_left_x_cm=top_left_x,
        top_left_y_cm=top_left_y,
        width_cm=width_cm,
        height_cm=height_cm,
    )
    validate_rect_in_canvas(grid, rect)
    return rect


def validate_rect_in_canvas(grid: Grid, rect: DeviceRect) -> None:
    """Validate that a device rectangle lies fully within the canvas."""
    eps = 1e-6
    if rect.top_left_x_cm < -eps or rect.top_left_y_cm < -eps:
        raise GridValidationError(400, "Device rectangle starts outside the canvas")
    if rect.top_left_x_cm + rect.width_cm > grid.width_cm + eps:
        raise GridValidationError(400, "Device rectangle extends past the canvas width")
    if rect.top_left_y_cm + rect.height_cm > grid.height_cm + eps:
        raise GridValidationError(400, "Device rectangle extends past the canvas height")


async def list_grid_devices(session: AsyncSession, grid_id: UUID) -> list[GridDevice]:
    """Return all placements for a grid."""
    result = await session.exec(select(GridDevice).where(col(GridDevice.grid_id) == grid_id))
    return list(result.all())


async def get_grid_or_404(session: AsyncSession, grid_id: UUID) -> Grid:
    """Fetch a grid by id, raising 404 if missing."""
    result = await session.exec(select(Grid).where(col(Grid.id) == grid_id))
    grid = result.first()
    if grid is None:
        raise HTTPException(status_code=404, detail="Grid not found")
    return grid


async def get_device_or_404(session: AsyncSession, device_id: UUID) -> Device:
    """Fetch a device by primary key, raising 404 if missing."""
    result = await session.exec(select(Device).where(col(Device.id) == device_id))
    device = result.first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


async def get_profile(session: AsyncSession, profile_id: UUID) -> DeviceProfile:
    """Fetch a device profile by id, raising 500 if missing (should not happen)."""
    result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == profile_id))
    profile = result.first()
    if profile is None:
        raise HTTPException(status_code=500, detail="Device profile not found")
    return profile


def compute_crop_for_device(
    image_data: bytes,
    grid: Grid,
    placement: GridDevice,
    target_pixel_size: tuple[int, int],
    *,
    quality: int = 85,
) -> bytes:
    """Crop and resize the source image to the device's slice.

    The source image is cover-fitted to the canvas (so it fully covers
    every cm of the grid, cropping overflow on one axis). The device's
    cm-rectangle then maps directly onto the projected region.

    Args:
        image_data: Source image bytes.
        grid: The grid the device is placed on.
        placement: The device's cm-rect on the grid.
        target_pixel_size: Final ``(width_px, height_px)`` for the device.
        quality: JPEG output quality.

    Returns:
        JPEG bytes sized to ``target_pixel_size``.

    """
    with PILImage.open(BytesIO(image_data)) as original:
        oriented = ImageOps.exif_transpose(original) or original
        rgb = oriented.convert("RGB") if oriented.mode != "RGB" else oriented.copy()

    img_w, img_h = rgb.size
    canvas_aspect = grid.width_cm / grid.height_cm
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

    px_per_cm_x = used_w / grid.width_cm
    px_per_cm_y = used_h / grid.height_cm

    crop_left = used_left + placement.top_left_x_cm * px_per_cm_x
    crop_top = used_top + placement.top_left_y_cm * px_per_cm_y
    crop_right = crop_left + placement.width_cm * px_per_cm_x
    crop_bottom = crop_top + placement.height_cm * px_per_cm_y

    cropped = rgb.crop((int(crop_left), int(crop_top), int(crop_right), int(crop_bottom)))
    resized = cropped.resize(target_pixel_size, resample=Resampling.LANCZOS)

    out = BytesIO()
    resized.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def grid_crop_storage_path(grid_id: UUID, image_id: UUID, device_id: UUID) -> str:
    """Build the S3 object key for a grid crop."""
    return f"grids/{grid_id}/{image_id}/{device_id}.jpg"


async def render_and_upload(
    session: AsyncSession,
    grid: Grid,
    image: Image,
    s3: S3Service,
) -> dict[UUID, str]:
    """Render per-device crops and upload them to S3.

    Returns a mapping ``device_id -> storage_path`` for each placement.
    """
    placements = await list_grid_devices(session, grid.id)
    if not placements:
        raise HTTPException(status_code=400, detail="Grid has no devices placed")

    source_bytes = _fetch_image_bytes(s3, image.storage_path)

    out: dict[UUID, str] = {}
    for placement in placements:
        device = await get_device_or_404(session, placement.device_id)
        profile = await get_profile(session, device.device_profile_id)
        target_size = oriented_pixel_dims(profile, device.display_orientation)
        crop_bytes = compute_crop_for_device(source_bytes, grid, placement, target_size)
        path = grid_crop_storage_path(grid.id, image.id, placement.device_id)
        s3.upload_image(path, crop_bytes, "image/jpeg")
        out[placement.device_id] = path
    return out


def _fetch_image_bytes(s3: S3Service, storage_path: str) -> bytes:
    """Download the source image bytes from S3."""
    # The s3 service wraps minio; reach through to its underlying client.
    client = s3._client
    bucket = s3._bucket
    response = client.get_object(bucket, storage_path)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def claim_devices_and_push(  # noqa: PLR0913 — explicit deps mirror the route call site
    session: AsyncSession,
    grid: Grid,
    image: Image,
    crop_paths: dict[UUID, str],
    mqtt: MQTTService,
    settings: Settings,
) -> None:
    """Claim every grid member device and push its slice via MQTT.

    Aborts (raises 409) without partial state changes if any member is
    already claimed by a different grid.
    """
    now = utcnow()
    placements = await list_grid_devices(session, grid.id)

    # Pre-flight: refuse if any member is held by another grid.
    devices: list[Device] = []
    for placement in placements:
        device = await get_device_or_404(session, placement.device_id)
        if device.claimed_by_grid_id is not None and device.claimed_by_grid_id != grid.id:
            raise HTTPException(
                status_code=409,
                detail=f"Device {device.device_id} is already claimed by another grid",
            )
        devices.append(device)

    # Apply claims and push commands. Cadence is grid-owned now — every
    # member tracks the same ``scheduled_next_at`` as the grid itself so
    # the rotation loop drives them in lockstep.
    default_seconds = await get_default_refresh_seconds(session, settings)
    grid_next = next_refresh_at(grid, default_seconds, now)
    for device in devices:
        path = crop_paths[device.id]
        device.claimed_by_grid_id = grid.id
        device.current_image_id = image.id
        device.displayed_since = now
        device.scheduled_next_at = grid_next
        device.updated_at = now
        session.add(device)

        if mqtt.is_connected(device.device_id):
            command = DisplayCommand(
                action="display",
                image_path=path,
                image_id=str(image.id),
                title=image.title,
            )
            try:
                await mqtt.send_command(device.device_id, command)
            except Exception:
                logger.exception("Failed to push grid command to %s", device.device_id)
        else:
            logger.info("Device %s offline; crop uploaded but command not delivered", device.device_id)

    grid.current_image_id = image.id
    grid.displayed_since = now
    grid.scheduled_next_at = grid_next
    grid.updated_at = now
    image.last_displayed_at = now
    session.add(grid)
    session.add(image)
    await session.commit()


async def release_grid(session: AsyncSession, grid: Grid) -> None:
    """Clear claims on every member device; the grid stops driving them."""
    placements = await list_grid_devices(session, grid.id)
    for placement in placements:
        device = await get_device_or_404(session, placement.device_id)
        if device.claimed_by_grid_id == grid.id:
            device.claimed_by_grid_id = None
            session.add(device)
    await session.commit()


async def get_next_grid_image(session: AsyncSession, grid: Grid) -> Image | None:
    """Pick the next image from the grid's pool (FIFO).

    Mirrors solo per-device rotation: never-shown images first, then by
    least-recently-shown.
    """
    query = (
        select(Image)
        .where(col(Image.target_grid_id) == grid.id)
        .order_by(col(Image.last_displayed_at).asc().nullsfirst())
        .limit(1)
    )
    result = await session.exec(query)
    return result.first()
