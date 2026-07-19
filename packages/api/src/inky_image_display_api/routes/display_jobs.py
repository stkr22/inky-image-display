"""Display-job configuration and control endpoints.

A display job (MOTD today, more content types later) generates content for
a grid on its own interval, mapping content parts onto the grid's layout
slots. These routes own job CRUD, manual generate/display, and the
generated-message history; the display schedule and session control live
on the grid routes.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from inky_image_display_shared.models import DisplayJob, DisplayJobSlot, Grid, MotdMessage, MotdScreen, PromptPreset
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.schemas.responses import (
    DisplayJobDisplayResult,
    DisplayJobResponse,
    DisplayJobSlotResponse,
    MotdMessageResponse,
    MotdScreenResponse,
)
from inky_image_display_shared.time import utcnow
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
            interval_minutes=body.interval_minutes,
        )
        if job.interval_minutes is not None:
            # Due immediately: a freshly created job should deliver right away.
            job.next_run_at = utcnow()
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
async def update_display_job(request: Request, job_id: UUID, body: DisplayJobUpdate) -> DisplayJobResponse:
    """Apply a partial job update; ``slots`` replaces the full mapping.

    Slot edits made while a session shows this job's content are applied to
    the running session immediately (missing screens rendered, changed slots
    re-pushed) — without this, edits silently do nothing until the next
    display start.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        previous_parts: dict[tuple[int, int], list[str]] = {}

        for field_name in ("name", "content_prompt", "source_mode", "text_model_name"):
            value = getattr(body, field_name)
            if value is not None:
                setattr(job, field_name, value)
        if body.clear_target_grid:
            job.target_grid_id = None
        elif body.target_grid_id is not None:
            job.target_grid_id = body.target_grid_id
        if body.clear_image_preset:
            job.image_preset_id = None
        elif body.image_preset_id is not None:
            job.image_preset_id = body.image_preset_id
        if body.clear_interval:
            job.interval_minutes = None
            job.next_run_at = None
        elif body.interval_minutes is not None:
            # Rebase the schedule on the new cadence (mirrors the sync jobs).
            job.interval_minutes = body.interval_minutes
            job.next_run_at = utcnow() + timedelta(minutes=body.interval_minutes)
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
        if body.slots is not None:
            # No-op unless a grid session is currently showing this job.
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
    """Delete a job; sessions showing its content are released first."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        message_ids = select(col(MotdMessage.id)).where(col(MotdMessage.job_id) == job.id)
        grids_result = await session.exec(select(Grid).where(col(Grid.active_message_id).in_(message_ids)))
        for grid in grids_result.all():
            await display_job_service.release_session(session, grid, request.app.state.settings)
        job = await _get_job_or_404(session, job_id)
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
    """Start a session on the job's target grid with its latest ready message.

    Passing ``message_id`` redisplays that retained message instead —
    the history list in the UI uses this. Session control (status, release)
    lives on the grid routes; this is the job-side convenience trigger.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        if job.target_grid_id is None:
            raise HTTPException(status_code=409, detail="The job has no target grid — pick one first")
        grid_id = job.target_grid_id
        message_id = body.message_id if body else None
        if message_id is None:
            # This job's newest ready message — not the grid's, so with two
            # jobs on one grid each Display button shows its own content.
            result = await session.exec(
                select(MotdMessage)
                .where(col(MotdMessage.job_id) == job.id, col(MotdMessage.status) == "ready")
                .order_by(col(MotdMessage.created_at).desc())
                .limit(1)
            )
            message = result.first()
            if message is None:
                raise HTTPException(status_code=409, detail="No generated message is ready — generate one first")
            message_id = message.id
    try:
        return await display_job_service.start_session(
            request.app.state.engine,
            request.app.state.mqtt,
            request.app.state.settings,
            request.app.state.s3_service,
            grid_id,
            message_id=message_id,
        )
    except JobStartError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
