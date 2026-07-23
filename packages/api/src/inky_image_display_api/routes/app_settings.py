"""Operator-tunable app settings endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import AppSettingsResponse, AppSettingsUpdate
from inky_image_display_api.services.app_settings_service import (
    get_default_refresh_seconds,
    get_quiet_hours,
    get_stagger_rotation,
    set_default_refresh_seconds,
    set_quiet_hours,
    set_stagger_rotation,
)

if TYPE_CHECKING:
    from inky_image_display_api.config import Settings

router = APIRouter(prefix="/api/app-settings", tags=["app-settings"])


async def _read_all(session: AsyncSession, settings: Settings) -> AppSettingsResponse:
    return AppSettingsResponse(
        default_refresh_seconds=await get_default_refresh_seconds(session, settings),
        quiet_hours=await get_quiet_hours(session),
        stagger_rotation=await get_stagger_rotation(session),
    )


@router.get("", response_model=AppSettingsResponse)
async def read_app_settings(request: Request) -> AppSettingsResponse:
    """Return all operator-tunable settings (default refresh, quiet hours, stagger)."""
    async with AsyncSession(request.app.state.engine) as session:
        return await _read_all(session, request.app.state.settings)


@router.put("", response_model=AppSettingsResponse)
async def update_app_settings(request: Request, body: AppSettingsUpdate) -> AppSettingsResponse:
    """Persist new operator-tunable settings; omitted sections are untouched."""
    async with AsyncSession(request.app.state.engine) as session:
        if body.default_refresh_seconds is not None:
            await set_default_refresh_seconds(session, body.default_refresh_seconds)
        if body.quiet_hours is not None:
            await set_quiet_hours(session, body.quiet_hours)
        if body.stagger_rotation is not None:
            await set_stagger_rotation(session, body.stagger_rotation)
        return await _read_all(session, request.app.state.settings)
