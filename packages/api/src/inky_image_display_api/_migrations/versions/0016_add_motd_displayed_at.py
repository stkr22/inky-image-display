"""Track when a MOTD message was last displayed.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-03

The message history UI lets operators redisplay any retained message; a
``displayed_at`` timestamp on ``motd_messages`` shows which stories were
already on the panels so the same one isn't shown twice by accident.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable displayed_at column."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "motd_messages" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("motd_messages")}
    if "displayed_at" not in existing:
        with op.batch_alter_table("motd_messages") as batch:
            batch.add_column(sa.Column("displayed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """One-way migration."""
    return
