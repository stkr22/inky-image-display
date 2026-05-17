"""Add per-device and per-grid refresh interval.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-17

Introduces ``refresh_interval_seconds`` on ``devices`` and ``grids``. A
``NULL`` value preserves today's behaviour (fall back to the global
``default_display_duration``); a populated value lets users dial the
cadence per entity from the UI.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Add nullable ``refresh_interval_seconds`` to devices and grids."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "devices" in tables and "refresh_interval_seconds" not in _columns(bind, "devices"):
        with op.batch_alter_table("devices") as batch:
            batch.add_column(sa.Column("refresh_interval_seconds", sa.Integer(), nullable=True))

    if "grids" in tables and "refresh_interval_seconds" not in _columns(bind, "grids"):
        with op.batch_alter_table("grids") as batch:
            batch.add_column(sa.Column("refresh_interval_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    """One-way migration."""
    return
