"""Album/person match modes for Immich sync jobs.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-18

Immich's search API intersects multi-value id filters, so multiple albums
or persons always meant AND. These columns let a job opt into OR ('any'):
the sync worker then unions one query per id. Default 'all' preserves the
behaviour of every existing job.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add match-mode columns to immich_sync_jobs."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "immich_sync_jobs" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("immich_sync_jobs")}
    with op.batch_alter_table("immich_sync_jobs") as batch:
        for column in ("album_match_mode", "person_match_mode"):
            if column not in existing:
                batch.add_column(sa.Column(column, sa.String(), nullable=False, server_default="all"))


def downgrade() -> None:
    """One-way migration."""
    return
