"""Unify display-job content onto image groups and a grid queue.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-20

Display jobs move to the same external-worker claim model as the sync
jobs: the worker generates a run's screens as ordinary ``images`` rows
bundled into an ``image_groups`` row targeting the grid. Grids replace the
MOTD session state with queue playback state (current group + frame +
hold), so scheduled displays, manual shows and pool rotation all run
through one queue.

The ``motd_messages``/``motd_screens`` tables are dropped without data
conversion: their content is ephemeral (7-day retention, regenerated on
the next worker run) and their S3 screens are orphaned harmlessly.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:  # noqa: PLR0912 — idempotent column-by-column guards
    """Create image_groups, extend images/grids/display_jobs, drop MOTD tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "image_groups" not in tables:
        op.create_table(
            "image_groups",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("target_grid_id", sa.Uuid(), sa.ForeignKey("grids.id", ondelete="SET NULL"), nullable=True),
            sa.Column(
                "display_job_id", sa.Uuid(), sa.ForeignKey("display_jobs.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("source_url", sa.String(), nullable=True),
            sa.Column("queue_position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_displayed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_image_groups_target_grid_id", "image_groups", ["target_grid_id"])
        op.create_index("ix_image_groups_display_job_id", "image_groups", ["display_job_id"])

    image_columns = {c["name"] for c in inspector.get_columns("images")}
    with op.batch_alter_table("images") as batch:
        if "group_id" not in image_columns:
            batch.add_column(sa.Column("group_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key("fk_images_group_id", "image_groups", ["group_id"], ["id"], ondelete="SET NULL")
        if "group_slot_row" not in image_columns:
            batch.add_column(sa.Column("group_slot_row", sa.Integer(), nullable=True))
        if "group_slot_col" not in image_columns:
            batch.add_column(sa.Column("group_slot_col", sa.Integer(), nullable=True))
        if "queue_position" not in image_columns:
            batch.add_column(sa.Column("queue_position", sa.Integer(), nullable=False, server_default="0"))
    if "group_id" not in image_columns:
        op.create_index("ix_images_group_id", "images", ["group_id"])

    grid_columns = {c["name"] for c in inspector.get_columns("grids")}
    with op.batch_alter_table("grids") as batch:
        if "current_group_id" not in grid_columns:
            batch.add_column(sa.Column("current_group_id", sa.Uuid(), nullable=True))
        if "current_frame" not in grid_columns:
            batch.add_column(sa.Column("current_frame", sa.Integer(), nullable=False, server_default="0"))
        if "hold_until" not in grid_columns:
            batch.add_column(sa.Column("hold_until", sa.DateTime(), nullable=True))
        for stale in ("active_message_id", "active_since", "active_expires_at"):
            if stale in grid_columns:
                batch.drop_column(stale)

    job_columns = {c["name"] for c in inspector.get_columns("display_jobs")}
    with op.batch_alter_table("display_jobs") as batch:
        if "is_active" not in job_columns:
            batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        if "run_requested_at" not in job_columns:
            batch.add_column(sa.Column("run_requested_at", sa.DateTime(), nullable=True))

    slot_columns = {c["name"] for c in inspector.get_columns("display_job_slots")}
    if "rotation_index" in slot_columns:
        with op.batch_alter_table("display_job_slots") as batch:
            batch.drop_column("rotation_index")

    with op.batch_alter_table("sync_job_runs") as batch:
        batch.alter_column("finished_at", existing_type=sa.DateTime(), nullable=True)

    for stale_table in ("motd_screens", "motd_messages"):
        if stale_table in tables:
            op.drop_table(stale_table)


def downgrade() -> None:
    """One-way migration."""
    return
