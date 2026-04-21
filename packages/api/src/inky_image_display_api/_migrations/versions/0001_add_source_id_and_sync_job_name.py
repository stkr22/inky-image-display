"""Add source_id + sync_job_name columns on images.

Revision ID: 0001
Revises:
Create Date: 2026-04-21

No data backfill: existing Immich records are expected to be cleared before
running this migration so the next sync populates the new columns correctly.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Add the new columns and index to the images table."""
    bind = op.get_bind()
    if "images" not in sa.inspect(bind).get_table_names():
        # Fresh DB: create_tables() will apply the full schema on startup.
        return

    existing = _columns(bind, "images")
    with op.batch_alter_table("images") as batch:
        if "source_id" not in existing:
            batch.add_column(sa.Column("source_id", sa.String(), nullable=True))
        if "sync_job_name" not in existing:
            batch.add_column(sa.Column("sync_job_name", sa.String(), nullable=True))

    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("images")}
    if "ix_images_source_id" not in indexes:
        op.create_index("ix_images_source_id", "images", ["source_id"], unique=False)


def downgrade() -> None:
    """Drop the source_id index and columns."""
    bind = op.get_bind()
    if "images" not in sa.inspect(bind).get_table_names():
        return

    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("images")}
    if "ix_images_source_id" in indexes:
        op.drop_index("ix_images_source_id", table_name="images")

    existing = _columns(bind, "images")
    with op.batch_alter_table("images") as batch:
        if "sync_job_name" in existing:
            batch.drop_column("sync_job_name")
        if "source_id" in existing:
            batch.drop_column("source_id")
