"""Helpers every job family shares once it has claimed its jobs.

Claiming is not free to undo: the API advances each job's schedule on
hand-out, and only the posted run report clears a job's "Run now" flag. So
after a claim, every job must get a run and a report, whatever fails in
between — an exception escaping the loop would silently drop the remaining
jobs until their next cron slot and leave the UI showing them as running.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from inky_image_display_shared.time import utcnow

from inky_image_display_sync.api_client import SyncRunReportPayload

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import datetime
    from uuid import UUID

    from inky_image_display_shared.schemas.responses import DeviceProfileResponse

    from inky_image_display_sync.api_client import DisplayAPIClient


class ClaimedJob(Protocol):
    """What the shared run loop needs to know about any job type."""

    @property
    def id(self) -> UUID: ...  # noqa: D102

    @property
    def name(self) -> str: ...  # noqa: D102


async def run_claimed[J: ClaimedJob, R](
    jobs: Sequence[J],
    *,
    run_one: Callable[[J], Awaitable[R]],
    on_error: Callable[[J, Exception], R],
    report: Callable[[J, R, datetime], Awaitable[None]],
    logger: logging.Logger,
) -> list[R]:
    """Run each claimed job in turn; a failure becomes that job's result.

    ``on_error`` turns an unexpected exception into the family's result type
    so ``report`` can post it like any other outcome.
    """
    results: list[R] = []
    for job in jobs:
        started_at = utcnow()
        try:
            result = await run_one(job)
        except Exception as exc:
            logger.exception("Job %s failed", job.name)
            result = on_error(job, exc)
        results.append(result)
        await report(job, result, started_at)
    return results


async def report_run(  # noqa: PLR0913 — mirrors the run-report payload
    api_client: DisplayAPIClient,
    *,
    job_type: str,
    job: ClaimedJob,
    started_at: datetime,
    errors: Sequence[str],
    detail: str | None,
    images_added: int = 0,
    images_skipped: int = 0,
    images_deleted: int = 0,
) -> None:
    """POST a run outcome so the UI can show last-run status per job."""
    await api_client.report_sync_run(
        SyncRunReportPayload(
            job_type=job_type,
            job_id=job.id,
            job_name=job.name,
            status="error" if errors else "success",
            started_at=started_at,
            finished_at=utcnow(),
            images_added=images_added,
            images_skipped=images_skipped,
            images_deleted=images_deleted,
            detail=detail,
            # Only the first few: the column is for a glance, the log has the rest.
            error="; ".join(errors[:3]) if errors else None,
        )
    )


def target_dims(profile: DeviceProfileResponse, portrait: bool) -> tuple[int, int]:
    """Return the ``(width, height)`` raster target for a profile.

    Profiles store panel-native landscape dimensions; a portrait image is the
    same panel rotated, so its target is the swapped pair.
    """
    return (profile.height, profile.width) if portrait else (profile.width, profile.height)


def expiry(days: int | None) -> datetime | None:
    """Return when an image registered now should expire, or None to keep it.

    Uses naive UTC because the API stores and compares expiries as naive UTC;
    local time would shift every expiry by the host's offset.
    """
    if days is None or days <= 0:
        return None
    return utcnow() + timedelta(days=days)
