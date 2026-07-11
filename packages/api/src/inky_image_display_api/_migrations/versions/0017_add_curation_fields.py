"""Curation controls: exclude-from-rotation, device pin, real duration override.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-11

``images.excluded_from_rotation`` lets operators veto an image from all
automatic rotation without deleting it; ``devices.is_pinned`` holds a
device on its current image. ``images.display_duration_seconds`` becomes
nullable and is nulled out wholesale: the column previously carried a dead
600s default that selection never consulted, so any stored value is
legacy noise — and once the scheduler starts honouring the override,
keeping those values would silently drop every device to a 10-minute
cadence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add curation columns and neutralise the legacy duration values."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "images" in tables:
        existing = {c["name"] for c in inspector.get_columns("images")}
        with op.batch_alter_table("images") as batch:
            if "excluded_from_rotation" not in existing:
                batch.add_column(
                    sa.Column(
                        "excluded_from_rotation",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    )
                )
            batch.alter_column("display_duration_seconds", existing_type=sa.Integer(), nullable=True)
        op.execute(sa.text("UPDATE images SET display_duration_seconds = NULL"))
        op.create_index(
            "ix_images_excluded_from_rotation",
            "images",
            ["excluded_from_rotation"],
            if_not_exists=True,
        )

    if "devices" in tables:
        existing = {c["name"] for c in inspector.get_columns("devices")}
        if "is_pinned" not in existing:
            with op.batch_alter_table("devices") as batch:
                batch.add_column(
                    sa.Column(
                        "is_pinned",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    )
                )


def downgrade() -> None:
    """One-way migration."""
    return
