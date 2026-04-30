"""Add ``last_seen`` column to ``devices``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-30

Adds a freshness timestamp the API bumps on every WS registration / ack.
The UI uses this to render online/offline self-healing — even if the
``is_online`` boolean flag is wrong (e.g. because of an old race between a
stale-disconnect handler and a live reconnect), the next message from the
device will refresh ``last_seen`` and the UI corrects within seconds.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _columns(bind: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    """Add ``devices.last_seen`` (defaults to the row's ``updated_at``)."""
    bind = op.get_bind()
    if "devices" not in sa.inspect(bind).get_table_names():
        return

    existing = _columns(bind, "devices")
    if "last_seen" in existing:
        return

    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("last_seen", sa.DateTime(), nullable=True))

    # Seed last_seen from updated_at so existing rows have a sensible value.
    bind.execute(sa.text("UPDATE devices SET last_seen = updated_at WHERE last_seen IS NULL"))

    with op.batch_alter_table("devices") as batch:
        batch.alter_column("last_seen", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    """Drop ``devices.last_seen``."""
    bind = op.get_bind()
    if "devices" not in sa.inspect(bind).get_table_names():
        return
    if "last_seen" not in _columns(bind, "devices"):
        return
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("last_seen")
