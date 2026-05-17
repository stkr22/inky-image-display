"""FIFO image selection for display devices."""

from datetime import datetime, timedelta

from inky_image_display_shared.models import Device, DeviceProfile, Grid, Image
from inky_image_display_shared.schemas import DisplayCommand
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.config import Settings


def next_refresh_at(entity: Device | Grid, settings: Settings, now: datetime) -> datetime:
    """Compute the next scheduled refresh time for a device or grid.

    ``refresh_interval_seconds`` on the entity wins; ``None`` falls back to
    ``settings.default_display_duration`` so untouched devices keep their
    historic behaviour.
    """
    seconds = entity.refresh_interval_seconds or settings.default_display_duration
    return now + timedelta(seconds=seconds)


async def get_next_image_for_device(session: AsyncSession, device: Device) -> Image | None:
    """Select the next image using FIFO with device compatibility filtering.

    Selection criteria:
    1. Images never displayed (``last_displayed_at IS NULL``) first.
    2. Then by least recently displayed (``last_displayed_at ASC``).
    3. Filtered by exact device-natural dimension match and orientation.

    Args:
        session: Active async database session.
        device: Target device record.

    Returns:
        Next image to display, or ``None`` when no suitable images exist.

    """
    is_portrait = device.display_orientation == "portrait"

    # Profile stores panel-native (landscape) dims. Image rows store
    # orientation-aware dims, so swap for portrait-mounted devices.
    profile_result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == device.device_profile_id))
    profile = profile_result.first()
    if profile is None:
        return None
    if is_portrait:
        expected_width, expected_height = profile.height, profile.width
    else:
        expected_width, expected_height = profile.width, profile.height

    query = (
        select(Image)
        .where(
            col(Image.original_width) == expected_width,
            col(Image.original_height) == expected_height,
            Image.is_portrait == is_portrait,
            col(Image.target_grid_id).is_(None),
        )
        .order_by(col(Image.last_displayed_at).asc().nullsfirst())
        .limit(1)
    )

    result = await session.exec(query)
    return result.first()


def build_display_command(image: Image) -> DisplayCommand:
    """Create a ``DisplayCommand`` for the given image.

    Args:
        image: Image to display.

    Returns:
        A display command ready to push over WebSocket.

    """
    return DisplayCommand(
        action="display",
        image_path=image.storage_path,
        image_id=str(image.id),
        title=image.title,
    )


async def update_display_state(
    session: AsyncSession,
    device: Device,
    image: Image,
    settings: Settings,
) -> None:
    """Update database after a display command has been sent.

    Args:
        session: Active async database session.
        device: Device that received the command.
        image: Image being displayed.
        settings: Application settings (for display duration).

    """
    now = utcnow()

    # Mark image as displayed
    image.last_displayed_at = now

    # Update device state
    device.current_image_id = image.id
    device.displayed_since = now
    device.scheduled_next_at = next_refresh_at(device, settings, now)
    device.updated_at = now

    session.add(image)
    session.add(device)
    await session.commit()
