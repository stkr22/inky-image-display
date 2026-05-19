"""Operator-tunable app settings endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import AppSettingsResponse, AppSettingsUpdate
from inky_image_display_api.services.app_settings_service import (
    get_default_refresh_seconds,
    set_default_refresh_seconds,
)

router = APIRouter(prefix="/api/app-settings", tags=["app-settings"])


@router.get("", response_model=AppSettingsResponse)
async def read_app_settings(request: Request) -> AppSettingsResponse:
    """Return all operator-tunable settings (currently: default refresh)."""
    settings = request.app.state.settings
    async with AsyncSession(request.app.state.engine) as session:
        seconds = await get_default_refresh_seconds(session, settings)
    return AppSettingsResponse(default_refresh_seconds=seconds)


@router.put("", response_model=AppSettingsResponse)
async def update_app_settings(request: Request, body: AppSettingsUpdate) -> AppSettingsResponse:
    """Persist new operator-tunable settings."""
    async with AsyncSession(request.app.state.engine) as session:
        seconds = await set_default_refresh_seconds(session, body.default_refresh_seconds)
    return AppSettingsResponse(default_refresh_seconds=seconds)
