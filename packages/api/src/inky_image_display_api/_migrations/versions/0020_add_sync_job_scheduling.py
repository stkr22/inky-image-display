"""Move sync-job cadence from deployment cron specs into the job rows.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-19

Previously each job family needed its own Kubernetes CronJob (plus a fast
--requested-only cron for the Run-now button). Storing interval/next-run on
the job row lets one frequent worker cron ask the API for due jobs, making
cadence operator-tunable from the UI.

Existing rows are backfilled with the cadences the deployment docs
recommended (hourly Immich, daily Gemini) and made due immediately so
nothing stops running across the upgrade.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_DEFAULT_INTERVAL_MINUTES = {"immich_sync_jobs": 60, "gemini_sync_jobs": 1440}


def upgrade() -> None:
    """Add interval_minutes / next_run_at / last_run_at to both job tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    now = datetime.now(UTC).replace(tzinfo=None)

    for table, default_interval in _DEFAULT_INTERVAL_MINUTES.items():
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            if "interval_minutes" not in existing:
                batch.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))
            if "next_run_at" not in existing:
                batch.add_column(sa.Column("next_run_at", sa.DateTime(), nullable=True))
            if "last_run_at" not in existing:
                batch.add_column(sa.Column("last_run_at", sa.DateTime(), nullable=True))
        op.execute(
            sa.text(f"UPDATE {table} SET interval_minutes = :interval WHERE interval_minutes IS NULL").bindparams(
                interval=default_interval
            )
        )
        op.execute(sa.text(f"UPDATE {table} SET next_run_at = :now WHERE next_run_at IS NULL").bindparams(now=now))


def downgrade() -> None:
    """One-way migration."""
    return
