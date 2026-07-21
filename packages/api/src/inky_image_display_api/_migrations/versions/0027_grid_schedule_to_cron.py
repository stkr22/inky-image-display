"""Replace the grid display time+weekday-mask schedule with cron.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-21

Grids adopt the same cron mechanism migration 0026 gave the jobs:
``display_time`` ("HH:MM") + ``display_weekday_mask`` (bit 0 = Monday)
become ``display_cron``, and the once-per-day ``last_displayed_on`` guard
becomes a ``display_next_at`` lease advanced along the cron grid.

The lease backfill preserves in-flight behaviour: if an enabled grid's
slot for today already passed but was not shown yet (API down over the
display time), the lease is set to the migration time so the first tick
fires it — matching what the old "not displayed today" check would do.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op
from cronsim import CronSim

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


_ALL_DAYS_MASK = 127


def mask_to_cron(display_time: str, weekday_mask: int) -> str:
    """Cron equivalent of the old HH:MM + weekday-bitmask schedule.

    Mask bit i is Monday+i; cron weekday 0 is Sunday, so bit i maps to
    cron day ``(i + 1) % 7``. A full mask collapses to ``*``.
    """
    hour, minute = (int(piece) for piece in display_time.split(":"))
    if weekday_mask & _ALL_DAYS_MASK == _ALL_DAYS_MASK:
        days = "*"
    else:
        days = ",".join(str((bit + 1) % 7) for bit in range(7) if weekday_mask & (1 << bit))
    return f"{minute} {hour} * * {days}"


def backfill_lease(
    cron: str,
    timezone: str,
    last_displayed_on: str | None,
    now: datetime,
) -> datetime:
    """Compute the initial ``display_next_at`` (naive UTC) for an enabled grid.

    Normally the next cron occurrence; but a slot earlier today that was
    never shown fires immediately, exactly like the old date-guard check.
    """
    local_now = now.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone))
    start_of_day = datetime.combine(local_now.date(), time(0, 0), tzinfo=local_now.tzinfo) - timedelta(minutes=1)
    first_today = next(CronSim(cron, start_of_day))
    missed_today = first_today.date() == local_now.date() and first_today <= local_now
    if missed_today and last_displayed_on != str(local_now.date()):
        return now
    return next(CronSim(cron, local_now)).astimezone(UTC).replace(tzinfo=None)


def upgrade() -> None:
    """Add display_cron/display_next_at, backfill, drop the old columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "grids" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("grids")}
    with op.batch_alter_table("grids") as batch:
        if "display_cron" not in existing:
            batch.add_column(sa.Column("display_cron", sa.String(), nullable=False, server_default="0 8 * * *"))
        if "display_next_at" not in existing:
            batch.add_column(sa.Column("display_next_at", sa.DateTime(), nullable=True))
    if "display_time" not in existing:
        return

    now = datetime.now(UTC).replace(tzinfo=None)
    rows = bind.execute(
        sa.text(
            "SELECT id, display_time, display_weekday_mask, display_timezone, "
            "display_schedule_enabled, last_displayed_on FROM grids"
        )
    ).fetchall()
    for row_id, display_time, weekday_mask, timezone, enabled, last_displayed_on in rows:
        cron = mask_to_cron(display_time, int(weekday_mask))
        lease = backfill_lease(cron, timezone, str(last_displayed_on) if last_displayed_on else None, now)
        bind.execute(
            sa.text("UPDATE grids SET display_cron = :cron, display_next_at = :lease WHERE id = :id").bindparams(
                cron=cron, lease=lease if enabled else None, id=row_id
            )
        )
    with op.batch_alter_table("grids") as batch:
        batch.drop_column("display_time")
        batch.drop_column("display_weekday_mask")
        batch.drop_column("last_displayed_on")


def downgrade() -> None:
    """One-way migration."""
    return
