"""Create device_profiles, seed lineup, switch devices/jobs to FK.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-15

Replaces the per-device hardware-spec columns (``display_width``,
``display_height``, ``display_model``) with a small fixed lineup of
panel profiles. Devices and jobs reference a profile by FK; orientation
stays on the device, optionally overridable per job.

Seeds the three currently shipping Inky Impression Spectra 6 panels with
deterministic UUIDs (``uuid5(NAMESPACE_DNS, key)``) so tests and prod
share the same primary keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


# Deterministic IDs so seeded rows have the same PK in every environment.
_PROFILE_NAMESPACE = uuid.NAMESPACE_DNS


def _profile_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(_PROFILE_NAMESPACE, f"inky-image-display.device_profile.{key}")


# Tuple fields: key, name, width, height, model, is_default.
_LINEUP: tuple[tuple[str, str, int, int, str, bool], ...] = (
    (
        "inky_impression_4_spectra6",
        'Inky Impression 4" Spectra 6',
        640,
        400,
        "inky_impression_4_spectra6",
        False,
    ),
    (
        "inky_impression_7_spectra6",
        'Inky Impression 7.3" Spectra 6',
        800,
        480,
        "inky_impression_7_spectra6",
        False,
    ),
    (
        "inky_impression_13_spectra6",
        'Inky Impression 13.3" Spectra 6',
        1600,
        1200,
        "inky_impression_13_spectra6",
        True,
    ),
)


def _tables(bind: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Create profile table, seed it, swap devices/jobs to profile FKs."""
    bind = op.get_bind()

    # --- 1. device_profiles table ------------------------------------------
    if "device_profiles" not in _tables(bind):
        op.create_table(
            "device_profiles",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("key", sa.String(), nullable=False, unique=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_device_profiles_key", "device_profiles", ["key"], unique=True)

    _seed_lineup(bind)

    profile_id_by_key = _fetch_profile_ids(bind)
    profile_id_by_dims = {(w, h, model): profile_id_by_key[key] for key, _, w, h, model, _ in _LINEUP}
    default_profile_id = next(profile_id_by_key[key] for key, _, _, _, _, is_default in _LINEUP if is_default)

    # --- 2. devices: add FK, backfill, drop legacy spec columns ------------
    _migrate_devices(bind, profile_id_by_dims, default_profile_id)

    # --- 3. immich_sync_jobs: target_device_id -> target_device_profile_id --
    if "immich_sync_jobs" in _tables(bind):
        _migrate_immich_sync_jobs(bind)

    # --- 4. gemini_sync_jobs: target_device_id + is_portrait swap ----------
    if "gemini_sync_jobs" in _tables(bind):
        _migrate_gemini_sync_jobs(bind)


def _seed_lineup(bind: sa.engine.Connection) -> None:
    """Insert the three Inky Impression Spectra 6 panels if missing."""
    profiles_tbl = sa.Table(
        "device_profiles",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("model", sa.String()),
        sa.Column("is_default", sa.Boolean()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    existing_keys = {row[0] for row in bind.execute(sa.text("SELECT key FROM device_profiles")).fetchall()}
    now = datetime.now()
    rows = [
        {
            "id": _profile_uuid(key),
            "key": key,
            "name": name,
            "width": width,
            "height": height,
            "model": model,
            "is_default": is_default,
            "created_at": now,
            "updated_at": now,
        }
        for key, name, width, height, model, is_default in _LINEUP
        if key not in existing_keys
    ]
    if rows:
        op.bulk_insert(profiles_tbl, rows)


def _fetch_profile_ids(bind: sa.engine.Connection) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for row in bind.execute(sa.text("SELECT id, key FROM device_profiles")).fetchall():
        out[row[1]] = _coerce_uuid(row[0])
    return out


def _migrate_devices(
    bind: sa.engine.Connection,
    profile_id_by_dims: dict[tuple[int, int, str], uuid.UUID],
    default_profile_id: uuid.UUID,
) -> None:
    if "devices" not in _tables(bind):
        return
    cols = _columns(bind, "devices")

    # Add the FK column (nullable for now so existing rows can be backfilled).
    if "device_profile_id" not in cols:
        op.add_column("devices", sa.Column("device_profile_id", sa.Uuid(), nullable=True))

    has_legacy = {"display_width", "display_height", "display_model"} & cols
    if has_legacy:
        rows = bind.execute(sa.text("SELECT id, display_width, display_height, display_model FROM devices")).fetchall()
        for row in rows:
            dev_id, width, height, model = row
            key = (int(width), int(height), str(model))
            target = profile_id_by_dims.get(key, default_profile_id)
            bind.execute(
                sa.text("UPDATE devices SET device_profile_id = :pid WHERE id = :did"),
                {"pid": _uuid_param(target, bind), "did": dev_id},
            )
    else:
        # Devices created on a fresh DB before the FK column existed: send them to default.
        bind.execute(
            sa.text("UPDATE devices SET device_profile_id = :pid WHERE device_profile_id IS NULL"),
            {"pid": _uuid_param(default_profile_id, bind)},
        )

    # SQLite needs batch mode to drop columns / alter NOT NULL.
    with op.batch_alter_table("devices") as batch:
        batch.alter_column(
            "device_profile_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        for legacy in ("display_width", "display_height", "display_model"):
            if legacy in cols:
                batch.drop_column(legacy)
        batch.create_foreign_key(
            "fk_devices_device_profile_id_device_profiles",
            "device_profiles",
            ["device_profile_id"],
            ["id"],
        )


def _migrate_immich_sync_jobs(bind: sa.engine.Connection) -> None:
    cols = _columns(bind, "immich_sync_jobs")
    if "target_device_profile_id" not in cols:
        op.add_column(
            "immich_sync_jobs",
            sa.Column("target_device_profile_id", sa.Uuid(), nullable=True),
        )
    if "orientation" not in cols:
        op.add_column(
            "immich_sync_jobs",
            sa.Column("orientation", sa.String(), nullable=True),
        )

    if "target_device_id" in cols:
        # Backfill profile FK from each job's current device.
        bind.execute(
            sa.text(
                """
                UPDATE immich_sync_jobs
                SET target_device_profile_id = (
                    SELECT device_profile_id FROM devices WHERE devices.id = immich_sync_jobs.target_device_id
                )
                WHERE target_device_profile_id IS NULL
                """
            )
        )

    with op.batch_alter_table("immich_sync_jobs") as batch:
        batch.alter_column(
            "target_device_profile_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        if "target_device_id" in cols:
            batch.drop_column("target_device_id")
        batch.create_foreign_key(
            "fk_immich_sync_jobs_target_device_profile_id_device_profiles",
            "device_profiles",
            ["target_device_profile_id"],
            ["id"],
        )


def _migrate_gemini_sync_jobs(bind: sa.engine.Connection) -> None:
    cols = _columns(bind, "gemini_sync_jobs")
    if "target_device_profile_id" not in cols:
        op.add_column(
            "gemini_sync_jobs",
            sa.Column("target_device_profile_id", sa.Uuid(), nullable=True),
        )
    if "orientation" not in cols:
        op.add_column(
            "gemini_sync_jobs",
            sa.Column("orientation", sa.String(), nullable=True),
        )

    if "target_device_id" in cols:
        bind.execute(
            sa.text(
                """
                UPDATE gemini_sync_jobs
                SET target_device_profile_id = (
                    SELECT device_profile_id FROM devices WHERE devices.id = gemini_sync_jobs.target_device_id
                )
                WHERE target_device_profile_id IS NULL
                """
            )
        )

    if "is_portrait" in cols:
        bind.execute(
            sa.text(
                "UPDATE gemini_sync_jobs SET orientation = CASE WHEN is_portrait THEN 'portrait' ELSE 'landscape' END"
                " WHERE orientation IS NULL"
            )
        )
    else:
        bind.execute(sa.text("UPDATE gemini_sync_jobs SET orientation = 'portrait' WHERE orientation IS NULL"))

    with op.batch_alter_table("gemini_sync_jobs") as batch:
        batch.alter_column(
            "target_device_profile_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        batch.alter_column(
            "orientation",
            existing_type=sa.String(),
            nullable=False,
        )
        if "target_device_id" in cols:
            batch.drop_column("target_device_id")
        if "is_portrait" in cols:
            batch.drop_column("is_portrait")
        batch.create_foreign_key(
            "fk_gemini_sync_jobs_target_device_profile_id_device_profiles",
            "device_profiles",
            ["target_device_profile_id"],
            ["id"],
        )


def _uuid_param(value: uuid.UUID, bind: sa.engine.Connection) -> object:
    """Render a UUID for use as a raw ``sa.text`` parameter.

    SQLAlchemy's bind processors only apply when the column type is known.
    Inside ``sa.text`` we pass parameters as plain values, so on SQLite
    (which stores UUIDs as 32-char hex via ``sa.Uuid``) we hand over the
    hex string; on PostgreSQL the native driver handles ``uuid.UUID``.
    """
    if bind.dialect.name == "sqlite":
        return value.hex
    return value


def _coerce_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, bytes):
        return uuid.UUID(bytes=value)
    return uuid.UUID(str(value))


def downgrade() -> None:
    """One-way migration: the legacy spec columns are gone for good."""
    return
