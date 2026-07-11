"""Operator-tunable app settings endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import AppSettingsResponse, AppSettingsUpdate
from inky_image_display_api.services.app_settings_service import (
    get_default_refresh_seconds,
    get_quiet_hours,
    set_default_refresh_seconds,
    set_quiet_hours,
)

router = APIRouter(prefix="/api/app-settings", tags=["app-settings"])


@router.get("", response_model=AppSettingsResponse)
async def read_app_settings(request: Request) -> AppSettingsResponse:
    """Return all operator-tunable settings (default refresh, quiet hours)."""
    settings = request.app.state.settings
    async with AsyncSession(request.app.state.engine) as session:
        seconds = await get_default_refresh_seconds(session, settings)
        quiet_hours = await get_quiet_hours(session)
    return AppSettingsResponse(default_refresh_seconds=seconds, quiet_hours=quiet_hours)


@router.put("", response_model=AppSettingsResponse)
async def update_app_settings(request: Request, body: AppSettingsUpdate) -> AppSettingsResponse:
    """Persist new operator-tunable settings; omitted sections are untouched."""
    settings = request.app.state.settings
    async with AsyncSession(request.app.state.engine) as session:
        if body.default_refresh_seconds is not None:
            await set_default_refresh_seconds(session, body.default_refresh_seconds)
        if body.quiet_hours is not None:
            await set_quiet_hours(session, body.quiet_hours)
        seconds = await get_default_refresh_seconds(session, settings)
        quiet_hours = await get_quiet_hours(session)
    return AppSettingsResponse(default_refresh_seconds=seconds, quiet_hours=quiet_hours)
