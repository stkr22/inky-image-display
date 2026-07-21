"""Drop grid interval-rotation state; grids are schedule-driven only.

Revision ID: 0025
Revises: 0024

Grids no longer rotate their queue on a refresh interval — they show one
queue entry per scheduled daily display (or operator action), hold it,
and release the panels back to solo rotation. Groups are frozen spreads
(one image per slot), so the frame cursor goes too. Grids left showing
content by the old rotation loop without a hold get an expired hold so
the first tick releases their panels.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_DROPPED = ("scheduled_next_at", "refresh_interval_seconds", "current_frame")


def upgrade() -> None:
    """Remove the rotation columns from grids."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    grid_columns = {c["name"] for c in inspector.get_columns("grids")}
    with op.batch_alter_table("grids") as batch:
        for name in _DROPPED:
            if name in grid_columns:
                batch.drop_column(name)
    # The old loop rotated content without a hold; under the new semantics
    # only hold expiry releases panels, so give such grids an already
    # expired hold. Deliberate indefinite holds (far-future) are kept.
    now = datetime.now(UTC).replace(tzinfo=None)
    op.execute(
        sa.text(
            "UPDATE grids SET hold_until = :now"
            " WHERE hold_until IS NULL AND (current_group_id IS NOT NULL OR current_image_id IS NOT NULL)"
        ).bindparams(now=now)
    )


def downgrade() -> None:
    """One-way migration."""
    return
