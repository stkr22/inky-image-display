"""REST endpoints for the fixed device-profile lineup.

Profiles are seeded by Alembic (see migration 0007). The lineup is not
user-extensible — only ``name`` is mutable, and any profile can be marked
as the global default (used by genai when no override is supplied).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from inky_image_display_shared.models import DeviceProfile
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import DeviceProfileResponse, DeviceProfileUpdate

router = APIRouter(prefix="/api/device-profiles", tags=["device-profiles"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[DeviceProfileResponse])
async def list_device_profiles(request: Request) -> list[DeviceProfile]:
    """List all seeded device profiles."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(DeviceProfile).order_by(col(DeviceProfile.width).asc()))
        return list(result.all())


@router.get("/{profile_id}", response_model=DeviceProfileResponse)
async def get_device_profile(request: Request, profile_id: UUID) -> DeviceProfile:
    """Fetch a single profile by UUID."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == profile_id))
        profile = result.first()
        if profile is None:
            raise HTTPException(status_code=404, detail="Device profile not found")
        return profile


@router.patch("/{profile_id}", response_model=DeviceProfileResponse)
async def update_device_profile(request: Request, profile_id: UUID, body: DeviceProfileUpdate) -> DeviceProfile:
    """Update the display name of a profile. Size/model/key are immutable."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == profile_id))
        profile = result.first()
        if profile is None:
            raise HTTPException(status_code=404, detail="Device profile not found")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(profile, key, value)
        profile.updated_at = utcnow()
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile


@router.post("/{profile_id}/set-default", response_model=DeviceProfileResponse)
async def set_default_device_profile(request: Request, profile_id: UUID) -> DeviceProfile:
    """Make this profile the global default; clears the flag on all others."""
    async with AsyncSession(request.app.state.engine) as session:
        result = await session.exec(select(DeviceProfile).where(col(DeviceProfile.id) == profile_id))
        profile = result.first()
        if profile is None:
            raise HTTPException(status_code=404, detail="Device profile not found")

        others = await session.exec(
            select(DeviceProfile).where(
                col(DeviceProfile.is_default).is_(True),
                col(DeviceProfile.id) != profile_id,
            )
        )
        now = utcnow()
        for other in others.all():
            other.is_default = False
            other.updated_at = now
            session.add(other)
        profile.is_default = True
        profile.updated_at = now
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return profile
