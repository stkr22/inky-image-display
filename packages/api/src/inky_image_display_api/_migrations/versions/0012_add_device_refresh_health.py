"""Add display-refresh health columns to devices.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-13

Adds ``last_refresh_ok``, ``last_error`` and ``last_error_at`` to ``devices``
so the API can persist the outcome reported in each device ack. Until now the
ack's ``successful_display_change``/``error`` were logged and dropped, leaving
a stuck display indistinguishable from a healthy one in the UI. All columns are
nullable; ``NULL`` ``last_refresh_ok`` means "no ack seen yet", so existing
rows need no backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Add nullable refresh-health columns to ``devices`` (idempotent)."""
    bind = op.get_bind()
    if "devices" not in set(sa.inspect(bind).get_table_names()):
        return

    existing = _columns(bind, "devices")
    to_add = [
        sa.Column("last_refresh_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
    ]
    with op.batch_alter_table("devices") as batch:
        for column in to_add:
            if column.name not in existing:
                batch.add_column(column)


def downgrade() -> None:
    """One-way migration."""
    return
