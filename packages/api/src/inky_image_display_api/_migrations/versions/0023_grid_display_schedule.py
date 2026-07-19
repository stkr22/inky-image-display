"""Move display scheduling and session state from display jobs onto grids.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-19

Display jobs become pure generators with the same interval/next-run cadence
as the sync jobs; the grid owns *when* generated content is shown and the
live session state. Decoupling the two clocks lets a job pre-generate
content (e.g. a week's worth on Monday) long before the grid displays it.

Existing scheduled jobs are backfilled to a daily generation interval, and
their display schedule + any active session move to their target grid.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_JOB_COLUMNS_DROPPED = (
    "schedule_enabled",
    "display_time",
    "weekday_mask",
    "timezone",
    "generation_lead_minutes",
    "display_duration_seconds",
    "active_message_id",
    "active_since",
    "active_expires_at",
    "last_generated_on",
    "last_displayed_on",
)

_GRID_COLUMNS_ADDED = (
    sa.Column("display_schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("display_time", sa.String(), nullable=False, server_default="08:00"),
    sa.Column("display_weekday_mask", sa.Integer(), nullable=False, server_default="127"),
    sa.Column("display_timezone", sa.String(), nullable=False, server_default="UTC"),
    sa.Column("display_duration_seconds", sa.Integer(), nullable=True),
    sa.Column("active_message_id", sa.Uuid(), nullable=True),
    sa.Column("active_since", sa.DateTime(), nullable=True),
    sa.Column("active_expires_at", sa.DateTime(), nullable=True),
    sa.Column("last_displayed_on", sa.Date(), nullable=True),
)


def upgrade() -> None:
    """Add grid display-schedule columns, migrate job schedules, slim job rows."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    now = datetime.now(UTC).replace(tzinfo=None)

    grid_columns = {c["name"] for c in inspector.get_columns("grids")}
    with op.batch_alter_table("grids") as batch:
        for column in _GRID_COLUMNS_ADDED:
            if column.name not in grid_columns:
                batch.add_column(column)

    job_columns = {c["name"] for c in inspector.get_columns("display_jobs")}

    # Copy each grid's schedule + session from the job targeting it (the
    # newest one wins if several do — before this migration the UI treated
    # target grids as effectively exclusive).
    if "schedule_enabled" in job_columns:
        op.execute(
            sa.text(
                """
                UPDATE grids SET
                    display_schedule_enabled = source.schedule_enabled,
                    display_time = source.display_time,
                    display_weekday_mask = source.weekday_mask,
                    display_timezone = source.timezone,
                    display_duration_seconds = source.display_duration_seconds,
                    active_message_id = source.active_message_id,
                    active_since = source.active_since,
                    active_expires_at = source.active_expires_at,
                    last_displayed_on = source.last_displayed_on
                FROM (
                    SELECT * FROM display_jobs job
                    WHERE job.target_grid_id IS NOT NULL
                      AND job.updated_at = (
                          SELECT MAX(peer.updated_at) FROM display_jobs peer
                          WHERE peer.target_grid_id = job.target_grid_id
                      )
                ) AS source
                WHERE grids.id = source.target_grid_id
                """
            )
        )

    with op.batch_alter_table("display_jobs") as batch:
        if "interval_minutes" not in job_columns:
            batch.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))
        if "next_run_at" not in job_columns:
            batch.add_column(sa.Column("next_run_at", sa.DateTime(), nullable=True))
        if "last_run_at" not in job_columns:
            batch.add_column(sa.Column("last_run_at", sa.DateTime(), nullable=True))

    # Previously-scheduled jobs generated once per day ahead of display time;
    # a daily interval due now preserves that without a gap.
    if "schedule_enabled" in job_columns:
        op.execute(
            sa.text(
                "UPDATE display_jobs SET interval_minutes = 1440, next_run_at = :now WHERE schedule_enabled = 1"
            ).bindparams(now=now)
        )

    with op.batch_alter_table("display_jobs") as batch:
        for name in _JOB_COLUMNS_DROPPED:
            if name in job_columns:
                batch.drop_column(name)


def downgrade() -> None:
    """One-way migration."""
    return
