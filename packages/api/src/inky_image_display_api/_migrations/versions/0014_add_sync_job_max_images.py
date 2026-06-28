"""Add per-job ``max_images`` cap to immich_sync_jobs.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-28

``max_images`` used to be a single global sync-service setting, so the first
job in a run could exhaust the whole budget and starve later jobs. It now lives
per job (counted against each job's own uploads via ``images.sync_job_name``).
Existing rows default to 10, matching the new model default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``max_images`` to ``immich_sync_jobs`` (idempotent)."""
    bind = op.get_bind()
    if "immich_sync_jobs" not in set(sa.inspect(bind).get_table_names()):
        return

    existing = {c["name"] for c in sa.inspect(bind).get_columns("immich_sync_jobs")}
    if "max_images" not in existing:
        op.add_column(
            "immich_sync_jobs",
            sa.Column("max_images", sa.Integer(), nullable=False, server_default="10"),
        )


def downgrade() -> None:
    """One-way migration."""
    return
