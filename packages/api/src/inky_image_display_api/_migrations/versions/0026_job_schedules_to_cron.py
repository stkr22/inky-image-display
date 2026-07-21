"""Replace minute-interval job cadence with cron expressions.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-21

The worker no longer polls on a Kubernetes cron; the API evaluates each
job's cron expression and wakes the worker over MQTT. Cron can't express
every arbitrary minute interval, so existing cadences are converted to
the nearest expressible schedule, anchored at the row's ``next_run_at``
wall-clock time so a "daily" job keeps firing at its established hour.
Rounding is logged per row; existing ``next_run_at`` values are kept, so
nothing fires early because of the upgrade.
"""

from __future__ import annotations

import logging
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_JOB_TABLES = ("immich_sync_jobs", "gemini_sync_jobs", "display_jobs")

_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 24 * 60
_MINUTES_PER_WEEK = 7 * 24 * 60


def _nearest(candidates: list[int], value: int) -> int:
    return min(candidates, key=lambda c: abs(c - value))


def interval_to_cron(minutes: int, anchor: datetime | None) -> str:
    """Best-effort cron equivalent of an every-N-minutes cadence.

    Sub-hourly and hourly steps must divide 60/24 to be a valid cron
    step, so odd values round to the nearest divisor. Daily and longer
    cadences keep the anchor's wall-clock time (and weekday for weekly)
    because that is the grid the job has been firing on.
    """
    minute = anchor.minute if anchor else 0
    hour = anchor.hour if anchor else 0
    if minutes < _MINUTES_PER_HOUR:
        step = _nearest([1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30], minutes)
        return f"*/{step} * * * *" if step > 1 else "* * * * *"
    if minutes < _MINUTES_PER_DAY:
        step = _nearest([1, 2, 3, 4, 6, 8, 12], round(minutes / _MINUTES_PER_HOUR))
        return f"{minute} */{step} * * *" if step > 1 else f"{minute} * * * *"
    if round(minutes / _MINUTES_PER_WEEK) == 1:
        weekday = anchor.isoweekday() % 7 if anchor else 0  # cron: 0 = Sunday
        return f"{minute} {hour} * * {weekday}"
    return f"{minute} {hour} * * *"


def upgrade() -> None:
    """Add schedule_cron/schedule_timezone, backfill, drop interval_minutes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in _JOB_TABLES:
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            if "schedule_cron" not in existing:
                batch.add_column(sa.Column("schedule_cron", sa.String(), nullable=True))
            if "schedule_timezone" not in existing:
                # Intervals were timezone-agnostic, so UTC preserves behaviour.
                batch.add_column(sa.Column("schedule_timezone", sa.String(), nullable=False, server_default="UTC"))
        if "interval_minutes" not in existing:
            continue

        rows = bind.execute(sa.text(f"SELECT id, interval_minutes, next_run_at FROM {table}")).fetchall()
        for row_id, interval, next_run_at in rows:
            if interval is None:
                continue
            anchor = datetime.fromisoformat(next_run_at) if isinstance(next_run_at, str) else next_run_at
            cron = interval_to_cron(int(interval), anchor)
            logger.info("%s %s: every %s min -> cron '%s'", table, row_id, interval, cron)
            bind.execute(
                sa.text(f"UPDATE {table} SET schedule_cron = :cron WHERE id = :id").bindparams(cron=cron, id=row_id)
            )
        with op.batch_alter_table(table) as batch:
            batch.drop_column("interval_minutes")


def downgrade() -> None:
    """One-way migration."""
    return
