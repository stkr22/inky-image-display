"""Drop per-job color/vibrancy thresholds from ``immich_sync_jobs``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-17

Sync jobs no longer apply client-side quality filters — they fetch, resize
via the API, and store. ``min_color_score`` and ``min_vibrancy_score`` are
now dead columns; this migration removes them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Drop the two threshold columns if they exist."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "immich_sync_jobs" not in tables:
        return

    existing = _columns(bind, "immich_sync_jobs")
    with op.batch_alter_table("immich_sync_jobs") as batch:
        if "min_color_score" in existing:
            batch.drop_column("min_color_score")
        if "min_vibrancy_score" in existing:
            batch.drop_column("min_vibrancy_score")


def downgrade() -> None:
    """Re-add both columns with the previous defaults."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "immich_sync_jobs" not in tables:
        return

    existing = _columns(bind, "immich_sync_jobs")
    with op.batch_alter_table("immich_sync_jobs") as batch:
        if "min_color_score" not in existing:
            batch.add_column(
                sa.Column("min_color_score", sa.Float(), nullable=False, server_default="0.5"),
            )
        if "min_vibrancy_score" not in existing:
            batch.add_column(
                sa.Column("min_vibrancy_score", sa.Float(), nullable=False, server_default="0.2"),
            )
