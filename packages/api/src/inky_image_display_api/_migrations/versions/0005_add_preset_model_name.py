"""Add ``model_name`` column to prompt_presets.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12

Previously the Gemini model id was hardcoded in ``ai/gemini.py``. Moving it
onto the preset row makes it editable via the API/UI without redeploying
and keeps the "complete prompt spec" idea consistent — a preset is now the
full bundle of blocks plus the model that should consume them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_DEFAULT_MODEL = "gemini-2.5-flash-image"


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Add ``prompt_presets.model_name`` and backfill existing rows."""
    bind = op.get_bind()
    if "prompt_presets" not in sa.inspect(bind).get_table_names():
        return
    if "model_name" in _columns(bind, "prompt_presets"):
        return

    with op.batch_alter_table("prompt_presets") as batch:
        batch.add_column(
            sa.Column(
                "model_name",
                sa.String(),
                nullable=False,
                server_default=_DEFAULT_MODEL,
            )
        )


def downgrade() -> None:
    """Drop ``prompt_presets.model_name``."""
    bind = op.get_bind()
    if "prompt_presets" not in sa.inspect(bind).get_table_names():
        return
    if "model_name" not in _columns(bind, "prompt_presets"):
        return
    with op.batch_alter_table("prompt_presets") as batch:
        batch.drop_column("model_name")
