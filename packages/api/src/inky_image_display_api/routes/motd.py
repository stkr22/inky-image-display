"""Message-of-the-day configuration and control endpoints."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from inky_image_display_shared.models import Device, MotdConfig, MotdDeviceAssignment, MotdMessage, MotdScreen
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.schemas.responses import (
    MotdAssignmentResponse,
    MotdConfigResponse,
    MotdDeviceStatus,
    MotdDisplayResult,
    MotdMessageResponse,
    MotdScreenResponse,
    MotdStatusResponse,
)
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import ImageGenerateResponse, MotdConfigUpdate
from inky_image_display_api.services import motd_service
from inky_image_display_api.services.generation_tasks import GenerationTaskRegistry
from inky_image_display_api.services.motd_service import MotdStartError

router = APIRouter(prefix="/api/motd", tags=["motd"])
logger = logging.getLogger(__name__)


def _task_registry(request: Request) -> GenerationTaskRegistry:
    """Return the app-wide task registry, creating it lazily (shared with genai)."""
    registry = getattr(request.app.state, "generation_tasks", None)
    if registry is None:
        registry = GenerationTaskRegistry()
        request.app.state.generation_tasks = registry
    return registry


def _config_response(config: MotdConfig, assignments: list[MotdDeviceAssignment]) -> MotdConfigResponse:
    return MotdConfigResponse(
        id=config.id,
        content_prompt=config.content_prompt,
        default_prompt=DEFAULT_MOTD_PROMPT,
        source_mode=config.source_mode,
        image_preset_id=config.image_preset_id,
        text_model_name=config.text_model_name,
        schedule_enabled=config.schedule_enabled,
        display_time=config.display_time,
        weekday_mask=config.weekday_mask,
        timezone=config.timezone,
        generation_lead_minutes=config.generation_lead_minutes,
        display_duration_seconds=config.display_duration_seconds,
        active_message_id=config.active_message_id,
        active_since=config.active_since,
        active_expires_at=config.active_expires_at,
        last_generated_on=config.last_generated_on,
        last_displayed_on=config.last_displayed_on,
        created_at=config.created_at,
        updated_at=config.updated_at,
        assignments=[
            MotdAssignmentResponse(
                device_id=a.device_id,
                parts=motd_service.parse_parts(a),
                rotation_index=a.rotation_index,
            )
            for a in assignments
        ],
    )


@router.get("/config")
async def get_config(request: Request) -> MotdConfigResponse:
    """Return the MOTD config, creating the singleton row on first access."""
    async with AsyncSession(request.app.state.engine) as session:
        config = await motd_service.get_or_create_config(session)
        assignments = await motd_service.list_assignments(session, config.id)
        return _config_response(config, assignments)


@router.put("/config")
async def update_config(request: Request, body: MotdConfigUpdate) -> MotdConfigResponse:
    """Apply a partial config update; ``assignments`` replaces the full list."""
    async with AsyncSession(request.app.state.engine) as session:
        config = await motd_service.get_or_create_config(session)

        for field_name in (
            "content_prompt",
            "source_mode",
            "text_model_name",
            "schedule_enabled",
            "display_time",
            "weekday_mask",
            "timezone",
            "generation_lead_minutes",
        ):
            value = getattr(body, field_name)
            if value is not None:
                setattr(config, field_name, value)
        if body.clear_image_preset:
            config.image_preset_id = None
        elif body.image_preset_id is not None:
            config.image_preset_id = body.image_preset_id
        if body.clear_display_duration:
            config.display_duration_seconds = None
        elif body.display_duration_seconds is not None:
            config.display_duration_seconds = body.display_duration_seconds
        session.add(config)

        if body.assignments is not None:
            device_ids = [a.device_id for a in body.assignments]
            if device_ids:
                known = await session.exec(select(Device.id).where(col(Device.id).in_(device_ids)))
                missing = set(device_ids) - set(known.all())
                if missing:
                    raise HTTPException(status_code=404, detail=f"Unknown devices: {sorted(map(str, missing))}")
            existing = await motd_service.list_assignments(session, config.id)
            for assignment in existing:
                await session.delete(assignment)
            for entry in body.assignments:
                session.add(
                    MotdDeviceAssignment(
                        config_id=config.id,
                        device_id=entry.device_id,
                        parts=json.dumps(entry.parts),
                    )
                )

        await session.commit()
        await session.refresh(config)
        assignments = await motd_service.list_assignments(session, config.id)
        return _config_response(config, assignments)


@router.post("/generate", status_code=202)
async def generate_now(request: Request, background_tasks: BackgroundTasks) -> ImageGenerateResponse:
    """Enqueue generation of a fresh message (story + image + screens)."""
    settings = request.app.state.settings
    if settings.gemini_api_key is None:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured on the server.")

    task_id = uuid4()
    tasks = _task_registry(request)
    tasks.create(task_id, "message of the day")
    background_tasks.add_task(
        motd_service.generate_message,
        request.app.state.engine,
        settings,
        request.app.state.s3_service,
        task_id=task_id,
        tasks=tasks,
    )
    logger.info("Queued MOTD generation task %s", task_id)
    return ImageGenerateResponse(task_id=task_id, status="queued")


@router.post("/display")
async def display_now(request: Request) -> MotdDisplayResult:
    """Start a display session with the latest ready message."""
    try:
        result = await motd_service.start_session(
            request.app.state.engine,
            request.app.state.mqtt,
            request.app.state.settings,
        )
    except MotdStartError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MotdDisplayResult(
        message_id=result.message_id,
        headline=result.headline,
        displayed=result.displayed,
        offline=result.offline,
        skipped_grid_claimed=result.skipped_grid_claimed,
        skipped_no_content=result.skipped_no_content,
    )


@router.post("/release")
async def release(request: Request) -> dict[str, str]:
    """End the active session; devices rejoin normal rotation immediately."""
    async with AsyncSession(request.app.state.engine) as session:
        config = await motd_service.get_or_create_config(session)
        await motd_service.release_session(session, config)
    return {"status": "released"}


@router.get("/status")
async def get_status(request: Request) -> MotdStatusResponse:
    """Report the active session and what each claimed device is showing."""
    async with AsyncSession(request.app.state.engine) as session:
        config = await motd_service.get_or_create_config(session)
        headline = None
        devices: list[MotdDeviceStatus] = []
        if config.active_message_id is not None:
            message_result = await session.exec(
                select(MotdMessage).where(col(MotdMessage.id) == config.active_message_id)
            )
            message = message_result.first()
            headline = message.headline if message else None
            screens = await motd_service.screens_by_part(session, config.active_message_id)
            for assignment in await motd_service.list_assignments(session, config.id):
                device_result = await session.exec(select(Device).where(col(Device.id) == assignment.device_id))
                device = device_result.first()
                if device is None or device.claimed_by_motd_config_id != config.id:
                    continue
                effective = await motd_service.effective_parts(session, assignment, screens)
                current = None
                if effective:
                    current = effective[assignment.rotation_index % len(effective)].part
                devices.append(
                    MotdDeviceStatus(device_id=device.device_id, is_online=device.is_online, current_part=current)
                )
        return MotdStatusResponse(
            active=config.active_message_id is not None,
            message_id=config.active_message_id,
            headline=headline,
            active_since=config.active_since,
            active_expires_at=config.active_expires_at,
            devices=devices,
        )


def _message_response(message: MotdMessage, screens: list[MotdScreen]) -> MotdMessageResponse:
    response = MotdMessageResponse.model_validate(message)
    response.screens = [MotdScreenResponse.model_validate(screen) for screen in screens]
    return response


@router.get("/messages/latest")
async def latest_message(request: Request) -> MotdMessageResponse | None:
    """Return the most recent message (any status) with its screens.

    ``null`` (not 404) when nothing was generated yet — the empty state is
    expected on every fresh install and a 404 would just be console noise.
    """
    async with AsyncSession(request.app.state.engine) as session:
        config = await motd_service.get_or_create_config(session)
        result = await session.exec(
            select(MotdMessage)
            .where(col(MotdMessage.config_id) == config.id)
            .order_by(col(MotdMessage.created_at).desc())
            .limit(1)
        )
        message = result.first()
        if message is None:
            return None
        screens_result = await session.exec(select(MotdScreen).where(col(MotdScreen.message_id) == message.id))
        return _message_response(message, list(screens_result.all()))


@router.get("/messages")
async def list_messages(request: Request, limit: int = 10) -> list[MotdMessageResponse]:
    """Return recent messages, newest first (without screens for brevity)."""
    async with AsyncSession(request.app.state.engine) as session:
        config = await motd_service.get_or_create_config(session)
        result = await session.exec(
            select(MotdMessage)
            .where(col(MotdMessage.config_id) == config.id)
            .order_by(col(MotdMessage.created_at).desc())
            .limit(max(1, min(limit, 50)))
        )
        return [_message_response(message, []) for message in result.all()]
