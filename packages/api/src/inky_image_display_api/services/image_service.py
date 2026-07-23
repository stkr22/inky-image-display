"""FIFO image selection for display devices."""

import random
from datetime import timedelta

from inky_image_display_shared.models import Device, DeviceProfile, Image
from inky_image_display_shared.schemas import DisplayCommand
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.config import Settings
from inky_image_display_api.services.app_settings_service import get_default_refresh_seconds

# How many least-recently-shown candidates the picker samples from. Strict
# oldest-first replays the pool in an identical order every cycle, which
# reads as repetitive even though nothing repeats early; a small random
# window breaks the sequence while keeping the LRU fairness guarantee (a
# just-shown image can't return until the pool has largely cycled).
_PICK_WINDOW = 5


async def get_next_image_for_device(session: AsyncSession, device: Device) -> Image | None:
    """Select the next image: random pick among the least-recently shown.

    Selection criteria:
    1. Images never displayed (``last_displayed_at IS NULL``) first.
    2. Then by least recently displayed (``last_displayed_at ASC``).
    3. Filtered by exact device-natural dimension match and orientation,
       excluding grid-pool images and operator-excluded images.
    4. A random choice among the top ``_PICK_WINDOW`` candidates.

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
            # Grouped images are shown via their group's grid queue, never solo.
            col(Image.group_id).is_(None),
            col(Image.excluded_from_rotation).is_(False),
        )
        .order_by(col(Image.last_displayed_at).asc().nullsfirst())
        .limit(_PICK_WINDOW)
    )

    result = await session.exec(query)
    candidates = list(result.all())
    if not candidates:
        return None
    return random.choice(candidates)


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
    )


async def update_display_state(
    session: AsyncSession,
    device: Device,
    image: Image,
    settings: Settings,
    stagger: tuple[int, int] | None = None,
) -> None:
    """Update database after a display command has been sent.

    Args:
        session: Active async database session.
        device: Device that received the command.
        image: Image being displayed.
        settings: Application settings (for display duration).
        stagger: Optional ``(index, count)``: spread simultaneously
            rotated panels' next refreshes evenly across the interval.

    """
    now = utcnow()
    default_seconds = await get_default_refresh_seconds(session, settings)

    # Mark image as displayed
    image.last_displayed_at = now

    # Update device state. A per-image hold time beats the device/global
    # interval so an operator can let a favourite linger without touching
    # the device's cadence.
    device.current_image_id = image.id
    device.displayed_since = now
    if image.display_duration_seconds is not None:
        device.scheduled_next_at = now + timedelta(seconds=image.display_duration_seconds)
    else:
        # Per-device override wins; None falls back to the operator default.
        next_at = now + timedelta(seconds=device.refresh_interval_seconds or default_seconds)
        if stagger is not None:
            index, count = stagger
            next_at = now + (next_at - now) * ((index + 1) / count)
        device.scheduled_next_at = next_at
    device.updated_at = now

    session.add(image)
    session.add(device)
    await session.commit()
