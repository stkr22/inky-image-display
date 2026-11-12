"""Device registration (HTTP ``/api/devices/register``).

Lives outside the MQTT transport module because it is request handling —
it raises HTTP errors and owns the reset-on-restart policy — not
transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException, status
from inky_image_display_shared.models import Device, DeviceProfile
from inky_image_display_shared.time import utcnow
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from inky_image_display_shared.schemas import DeviceRegistration
    from sqlalchemy.ext.asyncio import AsyncEngine


async def upsert_device(
    engine: AsyncEngine,
    device_id: str,
    registration: DeviceRegistration,
) -> Literal["registered", "updated"]:
    """Create or update a Device row; used by the HTTP /register endpoint."""
    async with AsyncSession(engine) as session:
        profile_result = await session.exec(
            select(DeviceProfile).where(DeviceProfile.key == registration.device_profile_key)
        )
        profile = profile_result.first()
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown device_profile_key '{registration.device_profile_key}'",
            )

        result = await session.exec(select(Device).where(Device.device_id == device_id))
        device = result.first()
        now = utcnow()

        if device is None:
            device = Device(
                device_id=device_id,
                room=registration.room,
                device_profile_id=profile.id,
                display_orientation=registration.orientation,
                is_online=False,  # Becomes True once we see the MQTT online status.
                last_seen=now,
            )
            session.add(device)
            outcome: Literal["registered", "updated"] = "registered"
        else:
            device.room = registration.room
            device.device_profile_id = profile.id
            device.display_orientation = registration.orientation
            device.last_seen = now
            # Registration happens exactly once per controller start, and the
            # controller's failed-refresh retry loop dies with the process. A
            # restart (e.g. the power cycle that recovers a latched panel)
            # means any recorded failure describes a controller that no longer
            # exists — reset to "no ack seen" so automatic dispatch resumes
            # and the next push settles the device's real state.
            device.last_refresh_ok = None
            device.last_error = None
            device.last_error_at = None
            session.add(device)
            outcome = "updated"

        await session.commit()
    return outcome
