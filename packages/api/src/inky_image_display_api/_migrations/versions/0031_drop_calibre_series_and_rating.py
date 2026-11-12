"""Drop the series and minimum-rating filters from Calibre bookshelf jobs.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-12

Both filters were fed by a rendered text blob that only Calibre-Web put into
its OPDS entries. The catalogue is now read from standard OPDS elements alone,
and the live Calibre-Web Automated feed carries neither series nor rating, so a
job using either filter could never match a book. Dropping the columns removes
a control that silently selects nothing; any values already stored in them are
discarded, and the downgrade restores empty columns only.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the filter columns that no catalogue can fill."""
    with op.batch_alter_table("calibre_sync_jobs") as batch:
        batch.drop_column("series")
        batch.drop_column("min_rating")


def downgrade() -> None:
    """Restore the columns, empty."""
    with op.batch_alter_table("calibre_sync_jobs") as batch:
        batch.add_column(sa.Column("series", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("min_rating", sa.Integer(), nullable=True))
