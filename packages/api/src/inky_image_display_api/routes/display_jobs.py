"""Display-job configuration and control endpoints.

A display job (MOTD today, more content types later) targets a grid and
maps generated content parts onto the grid's layout slots. These routes
own job CRUD, manual generate/display/release, live status, and the
generated-message history.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from inky_image_display_shared.models import DisplayJob, DisplayJobSlot, MotdMessage, MotdScreen, PromptPreset
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.schemas.responses import (
    DisplayJobDisplayResult,
    DisplayJobResponse,
    DisplayJobSlotResponse,
    DisplayJobSlotStatus,
    DisplayJobStatusResponse,
    MotdMessageResponse,
    MotdScreenResponse,
)
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    DisplayJobCreate,
    DisplayJobDisplayRequest,
    DisplayJobUpdate,
    ImageGenerateResponse,
)
from inky_image_display_api.services import display_job_service
from inky_image_display_api.services.display_job_service import MOTD_SCENE_PRESET_NAME, JobStartError
from inky_image_display_api.services.generation_tasks import task_registry

router = APIRouter(prefix="/api/display-jobs", tags=["display-jobs"])
logger = logging.getLogger(__name__)


def _job_response(job: DisplayJob, slots: list[DisplayJobSlot]) -> DisplayJobResponse:
    return DisplayJobResponse(
        **job.model_dump(),
        default_prompt=DEFAULT_MOTD_PROMPT,
        slots=[
            DisplayJobSlotResponse(
                row=slot.row,
                col=slot.col,
                parts=display_job_service.parse_parts(slot),
                rotation_index=slot.rotation_index,
            )
            for slot in slots
        ],
    )


async def _get_job_or_404(session: AsyncSession, job_id: UUID) -> DisplayJob:
    job = await session.get(DisplayJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Display job not found")
    return job


@router.get("")
async def list_display_jobs(request: Request) -> list[DisplayJobResponse]:
    """List all display jobs with their slot mappings."""
    async with AsyncSession(request.app.state.engine) as session:
        jobs = await display_job_service.list_jobs(session)
        return [_job_response(job, await display_job_service.list_slots(session, job.id)) for job in jobs]


@router.post("", status_code=201)
async def create_display_job(request: Request, body: DisplayJobCreate) -> DisplayJobResponse:
    """Create a display job.

    New MOTD jobs start on the seeded scene preset: MOTD image subjects are
    scene descriptions, and the scene composition renders them best. The
    library-wide default preset stays the portrait one, so the scene preset
    is looked up by name here instead.
    """
    async with AsyncSession(request.app.state.engine) as session:
        preset_result = await session.exec(select(PromptPreset).where(col(PromptPreset.name) == MOTD_SCENE_PRESET_NAME))
        scene_preset = preset_result.first()
        job = DisplayJob(
            name=body.name,
            job_type=body.job_type,
            target_grid_id=body.target_grid_id,
            image_preset_id=scene_preset.id if scene_preset else None,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        logger.info("Created display job %s (%s)", job.id, job.name)
        return _job_response(job, [])


@router.get("/{job_id}")
async def get_display_job(request: Request, job_id: UUID) -> DisplayJobResponse:
    """Fetch a single display job with its slot mapping."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        return _job_response(job, await display_job_service.list_slots(session, job.id))


@router.put("/{job_id}")
async def update_display_job(  # noqa: PLR0912 — one guarded branch per patchable section
    request: Request, job_id: UUID, body: DisplayJobUpdate
) -> DisplayJobResponse:
    """Apply a partial job update; ``slots`` replaces the full mapping.

    Slot edits made while a session is active are applied to the running
    session immediately (missing screens rendered, changed slots re-pushed)
    — without this, edits silently do nothing until the next display start.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        previous_parts: dict[tuple[int, int], list[str]] = {}

        for field_name in (
            "name",
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
                setattr(job, field_name, value)
        if body.clear_target_grid:
            job.target_grid_id = None
        elif body.target_grid_id is not None and body.target_grid_id != job.target_grid_id:
            if job.active_message_id is not None:
                raise HTTPException(status_code=409, detail="Release the active session before changing the grid")
            job.target_grid_id = body.target_grid_id
        if body.clear_image_preset:
            job.image_preset_id = None
        elif body.image_preset_id is not None:
            job.image_preset_id = body.image_preset_id
        if body.clear_display_duration:
            job.display_duration_seconds = None
        elif body.display_duration_seconds is not None:
            job.display_duration_seconds = body.display_duration_seconds
        session.add(job)

        if body.slots is not None:
            existing = await display_job_service.list_slots(session, job.id)
            previous_parts = {(s.row, s.col): display_job_service.parse_parts(s) for s in existing}
            for slot in existing:
                await session.delete(slot)
            for entry in body.slots:
                session.add(
                    DisplayJobSlot(
                        job_id=job.id,
                        row=entry.row,
                        col=entry.col,
                        parts=json.dumps(entry.parts),
                    )
                )

        await session.commit()
        await session.refresh(job)
        if body.slots is not None and job.active_message_id is not None:
            await display_job_service.resync_active_session(
                session,
                request.app.state.mqtt,
                request.app.state.settings,
                request.app.state.s3_service,
                job,
                previous_parts,
            )
            await session.refresh(job)
        return _job_response(job, await display_job_service.list_slots(session, job.id))


@router.delete("/{job_id}", status_code=204)
async def delete_display_job(request: Request, job_id: UUID) -> None:
    """Delete a job; an active session is released first so the grid is handed back."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        if job.active_message_id is not None:
            await display_job_service.release_session(session, job, request.app.state.settings)
            await session.refresh(job)
        await session.delete(job)
        await session.commit()
    logger.info("Deleted display job %s", job_id)


@router.post("/{job_id}/generate", status_code=202)
async def generate_now(request: Request, job_id: UUID, background_tasks: BackgroundTasks) -> ImageGenerateResponse:
    """Enqueue generation of fresh content (story + image + screens)."""
    settings = request.app.state.settings
    if settings.gemini_api_key is None:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured on the server.")
    async with AsyncSession(request.app.state.engine) as session:
        await _get_job_or_404(session, job_id)

    task_id = uuid4()
    tasks = task_registry(request)
    await tasks.create(task_id, "message of the day")
    background_tasks.add_task(
        display_job_service.generate_message,
        request.app.state.engine,
        settings,
        request.app.state.s3_service,
        job_id=job_id,
        task_id=task_id,
        tasks=tasks,
    )
    logger.info("Queued display-job generation task %s for job %s", task_id, job_id)
    return ImageGenerateResponse(task_id=task_id, status="queued")


@router.post("/{job_id}/display")
async def display_now(
    request: Request, job_id: UUID, body: DisplayJobDisplayRequest | None = None
) -> DisplayJobDisplayResult:
    """Start a display session with the latest ready message.

    Passing ``message_id`` redisplays that retained message instead —
    the history list in the UI uses this.
    """
    try:
        return await display_job_service.start_session(
            request.app.state.engine,
            request.app.state.mqtt,
            request.app.state.settings,
            request.app.state.s3_service,
            job_id,
            message_id=body.message_id if body else None,
        )
    except JobStartError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/release")
async def release(request: Request, job_id: UUID) -> dict[str, str]:
    """End the active session; the grid resumes rotation at a staggered time."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        await display_job_service.release_session(session, job, request.app.state.settings)
    return {"status": "released"}


@router.get("/{job_id}/status")
async def get_status(request: Request, job_id: UUID) -> DisplayJobStatusResponse:
    """Report the active session and what each grid slot is showing."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        headline = None
        slot_statuses: list[DisplayJobSlotStatus] = []
        if job.active_message_id is not None and job.target_grid_id is not None:
            message_result = await session.exec(select(MotdMessage).where(col(MotdMessage.id) == job.active_message_id))
            message = message_result.first()
            headline = message.headline if message else None
            screens = await display_job_service.screens_by_part(session, job.active_message_id)
            slot_targets = await display_job_service.resolve_slot_targets(session, job.target_grid_id)
            for slot in await display_job_service.list_slots(session, job.id):
                target = slot_targets.get((slot.row, slot.col))
                if target is None or target.device.claimed_by_grid_id != job.target_grid_id:
                    continue
                effective = display_job_service.effective_screens(
                    display_job_service.parse_parts(slot), target, screens
                )
                current = None
                if effective:
                    current = effective[slot.rotation_index % len(effective)].part
                slot_statuses.append(
                    DisplayJobSlotStatus(
                        row=slot.row,
                        col=slot.col,
                        device_id=target.device.device_id,
                        is_online=target.device.is_online,
                        current_part=current,
                    )
                )
        return DisplayJobStatusResponse(
            active=job.active_message_id is not None,
            message_id=job.active_message_id,
            headline=headline,
            active_since=job.active_since,
            active_expires_at=job.active_expires_at,
            slots=slot_statuses,
        )


def _message_response(message: MotdMessage, screens: list[MotdScreen]) -> MotdMessageResponse:
    response = MotdMessageResponse.model_validate(message)
    response.screens = [MotdScreenResponse.model_validate(screen) for screen in screens]
    return response


@router.get("/{job_id}/messages")
async def list_messages(request: Request, job_id: UUID, limit: int = 10) -> list[MotdMessageResponse]:
    """Return the job's recent messages with screens, newest first.

    Screens are included so the history list can expand any retained
    message into a full preview; retention keeps the list small.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        result = await session.exec(
            select(MotdMessage)
            .where(col(MotdMessage.job_id) == job.id)
            .order_by(col(MotdMessage.created_at).desc())
            .limit(max(1, min(limit, 50)))
        )
        messages = list(result.all())
        responses = []
        for message in messages:
            screens_result = await session.exec(select(MotdScreen).where(col(MotdScreen.message_id) == message.id))
            responses.append(_message_response(message, list(screens_result.all())))
        return responses
