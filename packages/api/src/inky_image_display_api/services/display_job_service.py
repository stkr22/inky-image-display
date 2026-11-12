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
from sqlmodel import and_, col, select

from inky_image_display_api.services import sync_job_scheduling
from inky_image_display_api.services.image_deletion import delete_images

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


def has_target_clause() -> ColumnElement[bool]:
    """Match jobs with a target grid; without one there is nothing to render."""
    return col(DisplayJob.target_grid_id).is_not(None)


def due_clause(now: datetime) -> ColumnElement[bool]:
    """Display jobs the worker should run (the shared predicate plus a target)."""
    return and_(has_target_clause(), sync_job_scheduling.due_clause(DisplayJob, now))


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
    if stale:
        images = await session.exec(select(Image).where(col(Image.group_id).in_([g.id for g in stale])))
        await delete_images(session, s3, list(images.all()))
    for group in stale:
        await session.delete(group)
    if stale:
        await session.commit()
