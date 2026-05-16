"""Add grid display target, device claims, and image grid pool.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-15

Introduces the grid feature: a virtual canvas grouping multiple devices to
display slices of a single source image. Adds physical-size metadata to
profiles, two new tables (``grids``, ``grid_devices``), and FK columns on
``devices`` and ``images`` so a device can be claimed by a grid and an image
can target a grid's rotation pool.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


# Pimoroni's published active-area specs for the seeded Spectra 6 panels.
# Stored as longer/shorter to match the landscape-native (width, height)
# convention used for pixel dimensions.
_PHYSICAL_DIMS: dict[str, tuple[float, float]] = {
    "inky_impression_4_spectra6": (8.5, 5.3),
    "inky_impression_7_spectra6": (16.3, 9.8),
    "inky_impression_13_spectra6": (27.1, 20.3),
}


def _tables(bind: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Add physical dims, create grid tables, add device/image FK columns."""
    bind = op.get_bind()

    _add_profile_physical_dims(bind)
    _create_grids_table(bind)
    _create_grid_devices_table(bind)
    _add_device_claim_column(bind)
    _add_image_target_grid_column(bind)


def _add_profile_physical_dims(bind: sa.engine.Connection) -> None:
    if "device_profiles" not in _tables(bind):
        return
    cols = _columns(bind, "device_profiles")
    with op.batch_alter_table("device_profiles") as batch:
        if "physical_width_cm" not in cols:
            batch.add_column(sa.Column("physical_width_cm", sa.Float(), nullable=False, server_default="0"))
        if "physical_height_cm" not in cols:
            batch.add_column(sa.Column("physical_height_cm", sa.Float(), nullable=False, server_default="0"))

    # Backfill the seeded panels with Pimoroni-published active-area dims.
    for key, (w_cm, h_cm) in _PHYSICAL_DIMS.items():
        bind.execute(
            sa.text(
                "UPDATE device_profiles "
                "SET physical_width_cm = :w, physical_height_cm = :h "
                "WHERE key = :key AND (physical_width_cm = 0 OR physical_width_cm IS NULL)"
            ),
            {"w": w_cm, "h": h_cm, "key": key},
        )


def _create_grids_table(bind: sa.engine.Connection) -> None:
    if "grids" in _tables(bind):
        return
    op.create_table(
        "grids",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("width_cm", sa.Float(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("current_image_id", sa.Uuid(), sa.ForeignKey("images.id"), nullable=True),
        sa.Column("displayed_since", sa.DateTime(), nullable=True),
        sa.Column("scheduled_next_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_grids_name", "grids", ["name"], unique=True)


def _create_grid_devices_table(bind: sa.engine.Connection) -> None:
    if "grid_devices" in _tables(bind):
        return
    op.create_table(
        "grid_devices",
        sa.Column("grid_id", sa.Uuid(), sa.ForeignKey("grids.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("top_left_x_cm", sa.Float(), nullable=False),
        sa.Column("top_left_y_cm", sa.Float(), nullable=False),
        sa.Column("width_cm", sa.Float(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def _add_device_claim_column(bind: sa.engine.Connection) -> None:
    if "devices" not in _tables(bind):
        return
    if "claimed_by_grid_id" in _columns(bind, "devices"):
        return
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("claimed_by_grid_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_devices_claimed_by_grid_id_grids",
            "grids",
            ["claimed_by_grid_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _add_image_target_grid_column(bind: sa.engine.Connection) -> None:
    if "images" not in _tables(bind):
        return
    if "target_grid_id" in _columns(bind, "images"):
        return
    with op.batch_alter_table("images") as batch:
        batch.add_column(sa.Column("target_grid_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_images_target_grid_id_grids",
            "grids",
            ["target_grid_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_images_target_grid_id", "images", ["target_grid_id"])


def downgrade() -> None:
    """One-way migration."""
    return
