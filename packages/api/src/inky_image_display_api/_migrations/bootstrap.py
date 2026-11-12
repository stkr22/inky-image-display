"""Base-table bootstrap that runs before the migrations.

The schema is hybrid: no migration creates the original base tables —
``create_all`` does, and the migrations apply incremental changes on top,
guarded to be no-ops on a fresh schema. This module is the single list of
those tables, shared by the app's startup and the bare Alembic CLI so
both build the same schema.
"""

from inky_image_display_shared import models  # noqa: F401 — registers every table on the metadata
from sqlalchemy import Connection
from sqlmodel import SQLModel

target_metadata = SQLModel.metadata

# Tables the migrations do NOT create, so create_all must. Everything else
# is deliberately excluded because a migration owns it: device_profiles and
# app_settings are seeded by 0007/0011 with their then-current columns (and
# later migrations add the rest), so pre-creating today's NOT NULL shape
# would break those seeds; calibre_sync_jobs and image_books are created
# by 0028/0032.
BOOTSTRAP_TABLES = (
    "images",
    "grids",
    "prompt_blocks",
    "prompt_presets",
    "devices",
    "grid_devices",
    "immich_sync_jobs",
    "gemini_sync_jobs",
    "display_jobs",
    "display_job_slots",
    "image_groups",
    "sync_job_runs",
    "generation_tasks",
)


def bootstrap_schema(connection: Connection) -> None:
    """Create any missing base tables; a no-op on an existing database.

    ``create_all`` sorts the given tables by foreign-key dependency, so the
    tuple above needs no particular order.
    """
    target_metadata.create_all(
        connection,
        tables=[target_metadata.tables[name] for name in BOOTSTRAP_TABLES],
        checkfirst=True,
    )
