"""Display-job configuration and worker hand-off endpoints.

A display job (MOTD today, more content types later) is configured here
and executed by the external worker: ``claim-due`` hands out due jobs
with their resolved panel slots, ``render-part`` turns the worker's
generated story into display-ready screens, and the worker registers the
result as an image group targeting the job's grid. Displaying groups
lives on the grid routes (queue / display-group / release).
"""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from inky_image_display_shared.models import DisplayJob, DisplayJobSlot, ImageGroup, PromptPreset
from inky_image_display_shared.motd import DEFAULT_MOTD_PROMPT
from inky_image_display_shared.schemas.responses import (
    DisplayJobClaim,
    DisplayJobClaimSlot,
    DisplayJobResponse,
    DisplayJobSlotResponse,
    GroupDisplayResult,
    ImageGroupResponse,
)
from inky_image_display_shared.time import utcnow
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from inky_image_display_api.schemas import (
    DisplayJobCreate,
    DisplayJobDisplayRequest,
    DisplayJobUpdate,
    MotdRenderRequest,
)
from inky_image_display_api.services import display_job_service, grid_service, motd_renderer, queue_service
from inky_image_display_api.services.display_job_service import MOTD_SCENE_PRESET_NAME
from inky_image_display_api.services.image_group_service import group_response
from inky_image_display_api.services.queue_service import QueueError
from inky_image_display_api.services.sync_job_scheduling import begin_runs, next_cron_run

router = APIRouter(prefix="/api/display-jobs", tags=["display-jobs"])
logger = logging.getLogger(__name__)


def _job_response(job: DisplayJob, slots: list[DisplayJobSlot]) -> DisplayJobResponse:
    return DisplayJobResponse(
        **job.model_dump(),
        default_prompt=DEFAULT_MOTD_PROMPT,
        slots=[
            DisplayJobSlotResponse(row=slot.row, col=slot.col, parts=display_job_service.parse_parts(slot))
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


@router.post("/claim-due")
async def claim_due_display_jobs(request: Request) -> list[DisplayJobClaim]:
    """Hand out due jobs to the worker with their resolved panel slots.

    Advances each job's schedule (lease semantics, like the sync jobs),
    records a ``running`` run row, and prunes the job's stale generated
    groups. Slots without a placed panel are omitted — the worker only
    renders what can actually show.
    """
    now = utcnow()
    claims: list[DisplayJobClaim] = []
    async with AsyncSession(request.app.state.engine) as session:
        jobs = await display_job_service.claim_due_jobs(session, now)
        await begin_runs(session, "display", [(j.id, j.name) for j in jobs], now)
        for job in jobs:
            await session.refresh(job)
            if job.target_grid_id is None:
                continue
            await display_job_service.prune_generated_groups(session, request.app.state.s3_service, job.id, now)
            targets = await grid_service.resolve_slot_targets(session, job.target_grid_id)
            slots = []
            for slot in await display_job_service.list_slots(session, job.id):
                target = targets.get((slot.row, slot.col))
                if target is None:
                    continue
                slots.append(
                    DisplayJobClaimSlot(
                        row=slot.row,
                        col=slot.col,
                        parts=display_job_service.parse_parts(slot),
                        device_id=target.device.device_id,
                        width=target.width,
                        height=target.height,
                        is_portrait=target.is_portrait,
                    )
                )
            claims.append(
                DisplayJobClaim(
                    id=job.id,
                    name=job.name,
                    target_grid_id=job.target_grid_id,
                    content_prompt=job.content_prompt,
                    source_mode=job.source_mode,
                    image_preset_id=job.image_preset_id,
                    text_model_name=job.text_model_name,
                    slots=slots,
                )
            )
    if claims:
        logger.info("Handed out %d due display job(s)", len(claims))
    return claims


@router.post("/render-part")
async def render_part(body: MotdRenderRequest) -> Response:
    """Render one story part at one panel size; returns JPEG bytes."""
    screen = motd_renderer.render_part(body.part, body, body.width, body.height)
    if screen is None:
        raise HTTPException(status_code=422, detail=f"Part {body.part!r} has no renderable content")
    return Response(content=screen, media_type="image/jpeg")


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
            schedule_cron=body.schedule_cron,
            schedule_timezone=body.schedule_timezone,
        )
        if job.schedule_cron is not None:
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

    Slot edits take effect on the worker's next generation — already
    generated groups keep the slot mapping they were rendered for.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)

        for field_name in ("name", "content_prompt", "source_mode", "text_model_name", "is_active"):
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
        if body.clear_schedule:
            job.schedule_cron = None
            job.next_run_at = None
        elif body.schedule_cron is not None or body.schedule_timezone is not None:
            # Rebase the schedule on the new cadence (mirrors the sync jobs).
            job.schedule_cron = body.schedule_cron or job.schedule_cron
            job.schedule_timezone = body.schedule_timezone or job.schedule_timezone
            if job.schedule_cron is not None:
                job.next_run_at = next_cron_run(job.schedule_cron, job.schedule_timezone, utcnow())
        session.add(job)

        if body.slots is not None:
            existing = await display_job_service.list_slots(session, job.id)
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
        return _job_response(job, await display_job_service.list_slots(session, job.id))


@router.delete("/{job_id}", status_code=204)
async def delete_display_job(request: Request, job_id: UUID) -> None:
    """Delete a job; its generated groups stay (provenance goes NULL)."""
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        await session.delete(job)
        await session.commit()
    logger.info("Deleted display job %s", job_id)


@router.post("/{job_id}/run-now")
async def request_display_job_run(request: Request, job_id: UUID) -> DisplayJobResponse:
    """Flag the job for an out-of-band worker run.

    The frequent worker cron claims flagged jobs (active or not — running
    a paused job on demand is the point of the button) and the posted run
    report clears the flag.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        if job.target_grid_id is None:
            raise HTTPException(status_code=409, detail="The job has no target grid — pick one first")
        job.run_requested_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
        logger.info("Run requested for display job %s (%s)", job_id, job.name)
        response = _job_response(job, await display_job_service.list_slots(session, job.id))
    await request.app.state.mqtt.publish_wake("display")
    return response


@router.post("/{job_id}/display")
async def display_now(
    request: Request, job_id: UUID, body: DisplayJobDisplayRequest | None = None
) -> GroupDisplayResult:
    """Show this job's latest generated group on its target grid now.

    Passing ``group_id`` redisplays that retained group instead — the
    history list in the UI uses this. Queue control (status, release)
    lives on the grid routes; this is the job-side convenience trigger.
    """
    async with AsyncSession(request.app.state.engine) as session:
        job = await _get_job_or_404(session, job_id)
        if job.target_grid_id is None:
            raise HTTPException(status_code=409, detail="The job has no target grid — pick one first")
        grid = await grid_service.get_grid_or_404(session, job.target_grid_id)

        group_id = body.group_id if body else None
        if group_id is not None:
            group = await session.get(ImageGroup, group_id)
            if group is None:
                raise HTTPException(status_code=404, detail="The requested group no longer exists")
        else:
            # This job's newest group — not the grid's, so with two jobs on
            # one grid each Display button shows its own content.
            result = await session.exec(
                select(ImageGroup)
                .where(col(ImageGroup.display_job_id) == job.id)
                .order_by(col(ImageGroup.created_at).desc())
                .limit(1)
            )
            group = result.first()
            if group is None:
                raise HTTPException(status_code=409, detail="No generated group exists yet — run the job first")
        try:
            return await queue_service.start_group(request.app, session, grid, group)
        except QueueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{job_id}/groups")
async def list_generated_groups(request: Request, job_id: UUID, limit: int = 10) -> list[ImageGroupResponse]:
    """Return the job's retained generated groups with images, newest first."""
    async with AsyncSession(request.app.state.engine) as session:
        await _get_job_or_404(session, job_id)
        result = await session.exec(
            select(ImageGroup)
            .where(col(ImageGroup.display_job_id) == job_id)
            .order_by(col(ImageGroup.created_at).desc())
            .limit(max(1, min(limit, 50)))
        )
        return [await group_response(session, group) for group in result.all()]
