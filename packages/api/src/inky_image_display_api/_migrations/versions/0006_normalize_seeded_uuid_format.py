"""Normalize 36-char dashed UUIDs in seeded AI tables to 32-char hex.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-13

Migration 0004 originally seeded ``prompt_blocks`` and ``prompt_presets`` with
``str(uuid.uuid4())`` (36-char with dashes) via ``sa.text(...)`` raw inserts.
SQLAlchemy's ``sa.Uuid`` column type on SQLite uses ``CHAR(32)`` and the bind
processor writes UUIDs as 32-char hex (no dashes). The result was a stored
format that the ORM's bind processor never produces, so ``where(col(id) ==
preset_id)`` lookups never matched — listing endpoints worked (no ID filter),
but on-demand generation and any FK join in Python code failed.

This migration rewrites affected columns in place. Idempotent: rows already
in 32-char hex form are left alone. Only runs on SQLite — Postgres uses the
native UUID type and is not affected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prompt_blocks", ("id",)),
    (
        "prompt_presets",
        (
            "id",
            "style_block_id",
            "palette_block_id",
            "legibility_block_id",
            "composition_block_id",
            "background_block_id",
        ),
    ),
    ("gemini_sync_jobs", ("prompt_preset_id",)),
)


def upgrade() -> None:
    """Strip dashes from 36-char UUID values in seeded AI tables."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        # Postgres et al. store UUIDs natively — no format drift possible.
        return

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _TARGETS:
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column not in existing_cols:
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = REPLACE({column}, '-', '') WHERE length({column}) = 36")
            )


def downgrade() -> None:
    """No-op: re-introducing dashes would only restore the original bug."""
    return
