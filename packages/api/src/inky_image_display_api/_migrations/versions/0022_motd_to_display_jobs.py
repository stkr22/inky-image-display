"""Restructure the MOTD into grid-targeting display jobs.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-19

The MOTD previously claimed devices directly (its own claim column and
per-device part assignments). Display jobs generalise it: a job targets a
grid, maps content parts onto the grid's layout slots, and reuses the
grid's claim/push machinery — new content formats become new job types
instead of new claim systems.

The existing MOTD config row is carried over as a display job with the
SAME id, so motd_messages only needs its FK column renamed. Device
assignments cannot be mapped to grid slots automatically (the devices were
never in a grid), so the operator re-targets the job at a grid in the UI;
any in-flight session state is cleared for the same reason.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create display job tables, migrate MOTD configs, drop the old claim system."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "display_jobs" not in tables:
        op.create_table(
            "display_jobs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("job_type", sa.String(), nullable=False, server_default="motd"),
            sa.Column("target_grid_id", sa.Uuid(), sa.ForeignKey("grids.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_prompt", sa.String(), nullable=False),
            sa.Column("source_mode", sa.String(), nullable=False, server_default="grounded"),
            sa.Column(
                "image_preset_id",
                sa.Uuid(),
                sa.ForeignKey("prompt_presets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("text_model_name", sa.String(), nullable=False, server_default="gemini-2.5-flash"),
            sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("display_time", sa.String(), nullable=False, server_default="08:00"),
            sa.Column("weekday_mask", sa.Integer(), nullable=False, server_default="127"),
            sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
            sa.Column("generation_lead_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("display_duration_seconds", sa.Integer(), nullable=True),
            sa.Column("active_message_id", sa.Uuid(), nullable=True),
            sa.Column("active_since", sa.DateTime(), nullable=True),
            sa.Column("active_expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_generated_on", sa.Date(), nullable=True),
            sa.Column("last_displayed_on", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "display_job_slots" not in tables:
        op.create_table(
            "display_job_slots",
            sa.Column("job_id", sa.Uuid(), sa.ForeignKey("display_jobs.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("row", sa.Integer(), primary_key=True),
            sa.Column("col", sa.Integer(), primary_key=True),
            sa.Column("parts", sa.String(), nullable=False, server_default="[]"),
            sa.Column("rotation_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    # Carry existing MOTD configs over as display jobs, keeping the id so
    # motd_messages rows stay attached after the column rename below.
    if "motd_configs" in tables:
        configs = bind.execute(
            sa.text(
                "SELECT id, content_prompt, source_mode, image_preset_id, text_model_name, "
                "schedule_enabled, display_time, weekday_mask, timezone, generation_lead_minutes, "
                "display_duration_seconds, last_generated_on, last_displayed_on, created_at, updated_at "
                "FROM motd_configs"
            )
        ).fetchall()
        for index, cfg in enumerate(configs):
            name = "Message of the day" if index == 0 else f"Message of the day {index + 1}"
            bind.execute(
                sa.text(
                    "INSERT INTO display_jobs (id, name, job_type, target_grid_id, content_prompt, source_mode, "
                    "image_preset_id, text_model_name, schedule_enabled, display_time, weekday_mask, timezone, "
                    "generation_lead_minutes, display_duration_seconds, active_message_id, active_since, "
                    "active_expires_at, last_generated_on, last_displayed_on, created_at, updated_at) "
                    "VALUES (:id, :name, 'motd', NULL, :content_prompt, :source_mode, :image_preset_id, "
                    ":text_model_name, :schedule_enabled, :display_time, :weekday_mask, :timezone, "
                    ":generation_lead_minutes, :display_duration_seconds, NULL, NULL, NULL, "
                    ":last_generated_on, :last_displayed_on, :created_at, :updated_at)"
                ).bindparams(
                    id=cfg.id,
                    name=name,
                    content_prompt=cfg.content_prompt,
                    source_mode=cfg.source_mode,
                    image_preset_id=cfg.image_preset_id,
                    text_model_name=cfg.text_model_name,
                    schedule_enabled=cfg.schedule_enabled,
                    display_time=cfg.display_time,
                    weekday_mask=cfg.weekday_mask,
                    timezone=cfg.timezone,
                    generation_lead_minutes=cfg.generation_lead_minutes,
                    display_duration_seconds=cfg.display_duration_seconds,
                    last_generated_on=cfg.last_generated_on,
                    last_displayed_on=cfg.last_displayed_on,
                    created_at=cfg.created_at,
                    updated_at=cfg.updated_at,
                )
            )

    # Rebuild motd_messages so config_id becomes job_id AND the FK points at
    # display_jobs — a plain column rename would leave the stored FK clause
    # referencing the dropped motd_configs table.
    if "motd_messages" in tables and "config_id" in {c["name"] for c in inspector.get_columns("motd_messages")}:
        op.rename_table("motd_messages", "motd_messages_old")
        op.create_table(
            "motd_messages",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("job_id", sa.Uuid(), sa.ForeignKey("display_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("headline", sa.String(), nullable=True),
            sa.Column("what", sa.String(), nullable=True),
            sa.Column("why", sa.String(), nullable=True),
            sa.Column("when_text", sa.String(), nullable=True),
            sa.Column("takeaway", sa.String(), nullable=True),
            sa.Column("image_subject", sa.String(), nullable=True),
            sa.Column("source_url", sa.String(), nullable=True),
            sa.Column("source_title", sa.String(), nullable=True),
            sa.Column("source_mode", sa.String(), nullable=False),
            sa.Column("displayed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.execute(
            "INSERT INTO motd_messages (id, job_id, status, error, headline, what, why, when_text, takeaway, "
            "image_subject, source_url, source_title, source_mode, displayed_at, created_at) "
            "SELECT id, config_id, status, error, headline, what, why, when_text, takeaway, "
            "image_subject, source_url, source_title, source_mode, displayed_at, created_at "
            "FROM motd_messages_old"
        )
        op.drop_table("motd_messages_old")

    # The direct device claim is superseded by the grid claim.
    if "devices" in tables:
        device_columns = {c["name"] for c in inspector.get_columns("devices")}
        if "claimed_by_motd_config_id" in device_columns:
            with op.batch_alter_table("devices") as batch:
                batch.drop_column("claimed_by_motd_config_id")

    if "motd_device_assignments" in tables:
        op.drop_table("motd_device_assignments")
    if "motd_configs" in tables:
        op.drop_table("motd_configs")


def downgrade() -> None:
    """One-way migration."""
    return
