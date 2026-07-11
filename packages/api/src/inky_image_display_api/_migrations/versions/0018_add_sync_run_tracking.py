"""Run-now flag for sync jobs (run history table is created at startup).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-11

``run_requested_at`` lets the UI queue an out-of-band worker run: the
"Run now" endpoint stamps it, a frequent ``--requested-only`` cron picks
flagged jobs up, and the posted run report clears it. The new
``sync_job_runs`` table needs no migration — brand-new tables are created
by the startup ``create_tables`` pass like every other table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the run_requested_at column to both job tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    for table in ("immich_sync_jobs", "gemini_sync_jobs"):
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        if "run_requested_at" not in existing:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("run_requested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """One-way migration."""
    return
