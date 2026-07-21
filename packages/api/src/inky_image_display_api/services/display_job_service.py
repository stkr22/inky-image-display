"""Display-job configuration and worker hand-off.

A display job is a pure content generator with the same claim model as
the sync jobs: the external worker claims due jobs (cron + next-run
lease, or a Run-now flag), generates the story and per-panel screens out
of process, and registers the result as an image group targeting the
job's grid. *Displaying* groups is the grid queue's business (see
``queue_service``) — nothing here touches a panel.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from inky_image_display_shared.models import DisplayJob, DisplayJobSlot, Grid, Image, ImageGroup
from sqlmodel import col, or_, select

from inky_image_display_api.services.sync_job_scheduling import next_cron_run

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import ColumnElement
    from sqlmodel.ext.asyncio.session import AsyncSession

    from inky_image_display_api.services.s3_service import S3Service

logger = logging.getLogger(__name__)

# Seeded preset (migration 0015) that new MOTD-type jobs default to.
MOTD_SCENE_PRESET_NAME = "e_ink_scene"

# Generated groups are kept this many days so operators can redisplay a
# recent story; older ones (images + S3 objects) are pruned at claim time.
# The newest group and any group currently on a grid survive regardless of
# age so "Display now" keeps working after a generation gap.
_RETENTION_DAYS = 7


def parse_parts(slot: DisplayJobSlot) -> list[str]:
    """Decode the JSON-encoded ordered part list."""
    try:
        parts = json.loads(slot.parts)
    except json.JSONDecodeError:
        return []
    return [p for p in parts if isinstance(p, str)]


async def list_jobs(session: AsyncSession) -> list[DisplayJob]:
    """Return all display jobs."""
    result = await session.exec(select(DisplayJob).order_by(col(DisplayJob.created_at)))
    return list(result.all())


async def list_slots(session: AsyncSession, job_id: UUID) -> list[DisplayJobSlot]:
    """Return all slot mappings for a job, in slot order."""
    result = await session.exec(
        select(DisplayJobSlot)
        .where(col(DisplayJobSlot.job_id) == job_id)
        .order_by(col(DisplayJobSlot.row), col(DisplayJobSlot.col))
    )
    return list(result.all())


def due_clause(now: datetime) -> ColumnElement[bool]:
    """Jobs the worker should run: Run-now flagged, or on-schedule and due.

    Mirrors the sync jobs' predicate; a job without a target grid has
    nothing to render for, so it never becomes due.
    """
    scheduled = (
        (col(DisplayJob.is_active).is_(True))
        & (col(DisplayJob.schedule_cron).is_not(None))
        & (col(DisplayJob.next_run_at) <= now)
    )
    return (col(DisplayJob.target_grid_id).is_not(None)) & or_(col(DisplayJob.run_requested_at).is_not(None), scheduled)


async def claim_due_jobs(session: AsyncSession, now: datetime) -> list[DisplayJob]:
    """Hand out due jobs and advance their schedules.

    Advancing ``next_run_at`` at hand-out doubles as a lease, exactly like
    the sync jobs' claim: only schedule-due jobs advance, along the fixed
    grid, so Run-now claims and late workers don't shift the cadence. The
    Run-now flag is cleared by the posted run report, so a worker that
    dies mid-run leaves the request armed.
    """
    result = await session.exec(select(DisplayJob).where(due_clause(now)))
    jobs = list(result.all())
    for job in jobs:
        if job.schedule_cron is not None and job.next_run_at is not None and job.next_run_at <= now:
            job.next_run_at = next_cron_run(job.schedule_cron, job.schedule_timezone, now)
            session.add(job)
    await session.commit()
    for job in jobs:
        await session.refresh(job)
    return jobs


async def prune_generated_groups(session: AsyncSession, s3: S3Service, job_id: UUID, now: datetime) -> None:
    """Delete this job's groups beyond retention, including image S3 objects.

    Runs at claim time — the moment fresh content is about to replace old —
    so the table can't grow unbounded without needing a separate cron.
    Commits.
    """
    cutoff = now - timedelta(days=_RETENTION_DAYS)
    showing_result = await session.exec(select(Grid.current_group_id).where(col(Grid.current_group_id).is_not(None)))
    showing_ids = set(showing_result.all())
    groups_result = await session.exec(
        select(ImageGroup).where(col(ImageGroup.display_job_id) == job_id).order_by(col(ImageGroup.created_at).desc())
    )
    groups = list(groups_result.all())
    newest_id = groups[0].id if groups else None
    stale = [g for g in groups if g.created_at < cutoff and g.id not in showing_ids and g.id != newest_id]
    for group in stale:
        images = await session.exec(select(Image).where(col(Image.group_id) == group.id))
        for image in images.all():
            try:
                s3.delete_object(image.storage_path)
            except Exception:
                logger.warning("Failed to delete group image object %s", image.storage_path)
            await session.delete(image)
        await session.delete(group)
    if stale:
        await session.commit()
