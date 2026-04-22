"""Retrofit sync'd images to the device-orientation convention.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-22

Images synced for portrait devices used to be stored with the processed
raster's landscape dimensions and ``is_portrait = False``. The new
convention records the device's natural orientation and dimensions so
orientation-aware queries match regardless of how the panel driver
rasterises on disk. This migration resolves each sync'd row through
``sync_job_name -> immich_sync_jobs.name -> target_device_id -> devices``
and flips dims / ``is_portrait`` for portrait devices.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_tables(bind: sa.engine.Connection, *tables: str) -> bool:
    existing = set(sa.inspect(bind).get_table_names())
    return all(table in existing for table in tables)


def upgrade() -> None:
    """Flip dims + is_portrait for images synced against portrait devices."""
    bind = op.get_bind()
    if not _has_tables(bind, "images", "immich_sync_jobs", "devices"):
        return

    bind.execute(
        sa.text(
            """
            UPDATE images
            SET
                original_width = original_height,
                original_height = original_width,
                is_portrait = TRUE
            WHERE id IN (
                SELECT images.id
                FROM images
                JOIN immich_sync_jobs ON immich_sync_jobs.name = images.sync_job_name
                JOIN devices ON devices.id = immich_sync_jobs.target_device_id
                WHERE devices.display_orientation = 'portrait'
                  AND images.is_portrait = FALSE
            )
            """,
        ),
    )


def downgrade() -> None:
    """Revert dims + is_portrait for portrait-device sync'd images."""
    bind = op.get_bind()
    if not _has_tables(bind, "images", "immich_sync_jobs", "devices"):
        return

    bind.execute(
        sa.text(
            """
            UPDATE images
            SET
                original_width = original_height,
                original_height = original_width,
                is_portrait = FALSE
            WHERE id IN (
                SELECT images.id
                FROM images
                JOIN immich_sync_jobs ON immich_sync_jobs.name = images.sync_job_name
                JOIN devices ON devices.id = immich_sync_jobs.target_device_id
                WHERE devices.display_orientation = 'portrait'
                  AND images.is_portrait = TRUE
            )
            """,
        ),
    )
