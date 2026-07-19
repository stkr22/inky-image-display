"""Slot addressing (row/col) for grid device placements.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-19

Grid placements are now computed from a tile layout instead of manually
entered cm coordinates. row/col are the stable slot address a display job
uses to map content onto panels. Existing placements are backfilled by
grouping on their stored Y coordinate (top-down) and ordering by X within
a group — the best available reconstruction of the visual arrangement.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add row/col slot columns to grid_devices and backfill from geometry."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "grid_devices" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("grid_devices")}
    with op.batch_alter_table("grid_devices") as batch:
        if "row" not in existing:
            batch.add_column(sa.Column("row", sa.Integer(), nullable=False, server_default="0"))
        if "col" not in existing:
            batch.add_column(sa.Column("col", sa.Integer(), nullable=False, server_default="0"))

    placements = bind.execute(
        sa.text("SELECT grid_id, device_id, top_left_x_cm, top_left_y_cm FROM grid_devices ORDER BY grid_id")
    ).fetchall()
    by_grid: dict[str, list] = {}
    for p in placements:
        by_grid.setdefault(str(p.grid_id), []).append(p)
    for members in by_grid.values():
        y_values = sorted({p.top_left_y_cm for p in members})
        for p in members:
            row = y_values.index(p.top_left_y_cm)
            col = sorted(
                (m.top_left_x_cm for m in members if m.top_left_y_cm == p.top_left_y_cm),
            ).index(p.top_left_x_cm)
            bind.execute(
                sa.text(
                    "UPDATE grid_devices SET row = :row, col = :col WHERE grid_id = :grid_id AND device_id = :device_id"
                ).bindparams(row=row, col=col, grid_id=p.grid_id, device_id=p.device_id)
            )


def downgrade() -> None:
    """One-way migration."""
    return
