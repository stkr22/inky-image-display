"""REST endpoints for device management."""

import logging
from typing import Annotated
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, HTTPException, Query, Request
from inky_image_display_shared.models import Device, DeviceProfile, Image
from inky_image_display_shared.schemas import DeviceRegistration, DisplayCommand, RegistrationResponse
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.mqtt import upsert_device
from inky_image_display_api.schemas import (
    DeviceResponse,
    DeviceUpdate,
    DisplayCommandRequest,
    ImageSummary,
    NextImageResponse,
)
from inky_image_display_api.services.image_processor import ImageProcessor
from inky_image_display_api.services.image_service import (
    build_display_command,
    get_next_image_for_device,
    update_display_state,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])
logger = logging.getLogger(__name__)


def _refresh_state(device: Device, backoff_seconds: int) -> str | None:
    """Classify refresh health so the UI can word guidance correctly.

    "failed_retrying" means the failure is younger than the dispatch
    backoff — the controller's own retry loop is presumed alive and the
    situation should self-heal. "failed_stale" means the failure has
    outlived the backoff without a success ack; at that point the retries
    have evidently not recovered the panel and the likely fix is physical
    (power cycle — see docs/refresh-issues.md).
    """
    if device.last_refresh_ok is None:
        return None
    if device.last_refresh_ok:
        return "ok"
    if device.last_error_at is None:
        return "failed_retrying"
    age = utcnow() - device.last_error_at
    return "failed_retrying" if age.total_seconds() <= backoff_seconds else "failed_stale"


async def _to_device_responses(
    session: AsyncSession, devices: list[Device], backoff_seconds: int
) -> list[DeviceResponse]:
    """Serialize devices with their current image embedded.

    One batched query resolves every ``current_image_id`` so list consumers
    can render thumbnails without a follow-up request per device.
    """
    image_ids = {d.current_image_id for d in devices if d.current_image_id is not None}
    images: dict[UUID, Image] = {}
    if image_ids:
        result = await session.exec(select(Image).where(col(Image.id).in_(image_ids)))
        images = {img.id: img for img in result.all()}
    responses = []
    for device in devices:
        response = DeviceResponse.model_validate(device)
        response.refresh_state = _refresh_state(device, backoff_seconds)
        image = images.get(device.current_image_id) if device.current_image_id else None
        if image is not None:
            response.current_image = ImageSummary.model_validate(image)
        responses.append(response)
    return responses


@router.post("/register")
async def register_device(request: Request, registration: DeviceRegistration) -> RegistrationResponse:
    """Upsert a device record and return the S3 reader credentials.

    Devices call this once on startup before connecting to MQTT. Online
    state is no longer set here — that arrives shortly after via the
    retained ``inky/devices/{id}/status`` topic.
    """
    settings = request.app.state.settings
    status = await upsert_device(request.app.state.engine, registration.device_id, registration)
    logger.info("Device %s registered (status=%s)", registration.device_id, status)
    return RegistrationResponse(
        status=status,
        s3_endpoint=settings.s3_endpoint,
        s3_bucket=settings.s3_bucket,
        s3_access_key=settings.s3_reader_access_key,
        s3_secret_key=settings.s3_reader_secret_key,
        s3_secure=settings.s3_secure,
        s3_region=settings.s3_region,
        mqtt_host=settings.device_mqtt_host,
        mqtt_port=settings.device_mqtt_port,
        mqtt_username=settings.device_mqtt_username,
        mqtt_password=(
            settings.device_mqtt_password.get_secret_value() if settings.device_mqtt_password is not None else None
        ),
        mqtt_tls=settings.device_mqtt_tls,
        mqtt_transport=settings.device_mqtt_transport,
        mqtt_websocket_path=settings.device_mqtt_websocket_path,
        mqtt_keep_alive=settings.device_mqtt_keep_alive,
    )


@router.get("")
async def list_devices(
    request: Request,
    room: Annotated[str | None, Query(description="Filter by room name")] = None,
    is_online: Annotated[bool | None, Query(description="Filter by online status")] = None,
    id: Annotated[UUID | None, Query(description="Filter by device primary-key UUID")] = None,
) -> list[DeviceResponse]:
    """List registered devices with optional filters.

    ``is_online`` reflects the broker's view of the device, kept fresh
    by retained MQTT status messages plus Last-Will-on-disconnect.
    """
    async with AsyncSession(request.app.state.engine) as session:
        stmt = select(Device)
        if room is not None:
            stmt = stmt.where(Device.room == room)
        if id is not None:
            stmt = stmt.where(col(Device.id) == id)
        if is_online is not None:
            stmt = stmt.where(Device.is_online == is_online)
        result = await session.exec(stmt)
        return await _to_device_responses(
            session, list(result.all()), request.app.state.settings.refresh_error_backoff_seconds
        )


@router.get("/{device_id}")
async def get_device(request: Request, device_id: str) -> DeviceResponse:
    """Get a device by its string identifier."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return (
            await _to_device_responses(session, [device], request.app.state.settings.refresh_error_backoff_seconds)
        )[0]


@router.patch("/{device_id}")
async def update_device(request: Request, device_id: str, body: DeviceUpdate) -> DeviceResponse:
    """Update editable device fields.

    Exposes the rotation cadence (pass ``clear_refresh_interval=True`` to
    reset the override back to the global default) and the pin flag that
    holds the current image. Other device fields (room, orientation,
    profile) are managed via registration. Validation of the seconds range
    happens in the schema layer.
    """
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        if body.clear_refresh_interval:
            device.refresh_interval_seconds = None
        elif body.refresh_interval_seconds is not None:
            device.refresh_interval_seconds = body.refresh_interval_seconds
        if body.is_pinned is not None:
            device.is_pinned = body.is_pinned
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return (
            await _to_device_responses(session, [device], request.app.state.settings.refresh_error_backoff_seconds)
        )[0]


async def _panel_dimensions(session: AsyncSession, device: Device) -> tuple[int, int]:
    """Orientation-aware pixel dimensions the panel expects."""
    result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == device.device_profile_id))
    profile = result.first()
    if profile is None:
        raise HTTPException(status_code=500, detail="Device has no profile")
    if device.display_orientation == "portrait":
        return profile.height, profile.width
    return profile.width, profile.height


def _fit_image_to_panel(s3, storage_path: str, width: int, height: int) -> str:
    """Cover-crop a stored image to exact panel dims; return the derived key.

    Derived copies live under ``derived/`` keyed by target size, so
    repeated sends of the same image to the same panel reuse the first
    crop. They are not registered as library images — the library keeps
    one logical picture, not one row per panel size.
    """
    derived_key = f"derived/{width}x{height}/{storage_path}"
    try:
        s3.stat_object(derived_key)
    except Exception:
        original = s3.get_object_bytes(storage_path)
        processed = ImageProcessor.process_for_display(original, width, height, upscale=True)
        if processed is None:
            raise HTTPException(status_code=422, detail="Image could not be fitted to the panel") from None
        s3.upload_image(derived_key, processed, "image/jpeg")
    return derived_key


@router.post("/{device_id}/display")
async def send_display_command(
    request: Request,
    device_id: str,
    body: DisplayCommandRequest,
) -> dict[str, str]:
    """Send a specific image to a connected device.

    The controller can only show exactly panel-sized rasters, so
    dimension mismatches are either resolved server-side (``fit="auto"``:
    cover-crop a derived copy) or rejected with 409 (``fit="exact"``) —
    never forwarded, since the panel would ack a failure and the device
    would wrongly enter the stuck-refresh backoff.

    Args:
        request: Incoming HTTP request.
        device_id: Target device string identifier.
        body: Request containing the image UUID to display and fit mode.

    """
    manager = request.app.state.mqtt
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    async with AsyncSession(request.app.state.engine) as session:
        # Fetch device
        dev_result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = dev_result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        # Fetch image
        img_result = await session.exec(select(Image).where(col(Image.id) == body.image_id))
        image = img_result.first()
        if image is None:
            raise HTTPException(status_code=404, detail="Image not found")

        expected_width, expected_height = await _panel_dimensions(session, device)
        matches = image.original_width == expected_width and image.original_height == expected_height

        if matches:
            command = build_display_command(image)
        elif body.fit == "auto":
            s3 = request.app.state.s3_service
            storage_path = image.storage_path
            derived_key = await to_thread.run_sync(
                _fit_image_to_panel, s3, storage_path, expected_width, expected_height
            )
            command = build_display_command(image)
            command.image_path = derived_key
        else:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Image is {image.original_width}x{image.original_height} but the panel needs "
                    f"{expected_width}x{expected_height}. Retry with fit='auto' to send a cover-cropped copy."
                ),
            )

        await manager.send_command(device_id, command)
        await update_display_state(session, device, image, request.app.state.settings)

    return {"status": "ok"}


@router.post("/{device_id}/next")
async def next_image(request: Request, device_id: str) -> NextImageResponse:
    """Trigger FIFO image selection and push to device.

    Returns image metadata so callers can build responses without a second request.
    """
    manager = request.app.state.mqtt
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    async with AsyncSession(request.app.state.engine) as session:
        dev_result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = dev_result.first()
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")

        image = await get_next_image_for_device(session, device)
        if image is None:
            raise HTTPException(status_code=404, detail="No suitable image available")

        # Capture attributes before commit expires the instance
        response = NextImageResponse(
            status="ok",
            image_id=image.id,
            title=image.title,
            description=image.description,
            source_name=image.source_name,
            author=image.author,
        )

        command = build_display_command(image)
        await manager.send_command(device_id, command)
        await update_display_state(session, device, image, request.app.state.settings)

        return response


@router.post("/{device_id}/clear")
async def clear_device(request: Request, device_id: str) -> dict[str, str]:
    """Send a clear command to the device."""
    manager = request.app.state.mqtt
    if not manager.is_connected(device_id):
        raise HTTPException(status_code=404, detail="Device not connected")

    command = DisplayCommand(action="clear")
    await manager.send_command(device_id, command)
    return {"status": "ok"}
