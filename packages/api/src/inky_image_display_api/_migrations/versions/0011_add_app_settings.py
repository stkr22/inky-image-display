"""Add ``app_settings`` key/value table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-19

Introduces a small key/value table for operator-tunable app settings,
starting with the global default refresh interval. Storing values as
JSON-encoded text keeps a single column type while supporting future
scalar settings without further migrations.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``app_settings`` table when absent."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_settings" in set(inspector.get_table_names()):
        return

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), primary_key=True, nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """One-way migration."""
    return
