"""Create prompt_blocks, prompt_presets, gemini_sync_jobs + seed defaults.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12

Adds the AI image-generation schema: a library of reusable prompt blocks,
named presets that compose one block per concern, and a Gemini sync job
table mirroring ``immich_sync_jobs``. Seeds the block library from the
constants originally embedded in ``packages/sync/scripts/gemini_pixel_art.py``
so a default preset (``e_ink_humanoid``) is usable out of the box.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# --- Seed content (matches gemini_pixel_art.py defaults) -------------------

_STYLE_DEFAULT = (
    "High-contrast poster / screen-print aesthetic: strong clear outlines, "
    "flat color blocks, simple chunky shapes, no photorealism. "
    "Van-Gogh-inspired color energy — saturated, dramatic complementary "
    "color blocking."
)

_PALETTE_SPECTRA_6 = (
    "Use only six colors: black, white, bold red, bright yellow, deep royal "
    "blue, and forest green used sparingly. Avoid muddy olive, beige, "
    "brown, teal, purple, pink, or any desaturated mid-tones."
)

_LEGIBILITY_EINK = (
    "Target medium is a 6-color e-ink display. Avoid gradients, soft "
    "shading, thin lines, wispy hair, fine textures, or any detail that "
    "would be lost with a limited palette — every feature must stay "
    "legible as bold shapes."
)

_COMPOSITION_HUMANOID = (
    "Tight close-up composition: the subject fills the frame edge to "
    "edge. Head reaches near the top of the image, shoulders span the "
    "full width, no empty margins around the portrait. Behind the "
    "subject, optionally place one or two iconic objects, symbols, or "
    "motifs associated with {subject} — rendered as large bold flat "
    "shapes or simplified illustrations behind the portrait, not a wide "
    "environmental scene and not fiddly detail."
)

_COMPOSITION_SCENE = (
    "Full-frame scene composition: {subject} occupies the central focus "
    "with surrounding context filling the frame edge to edge. Compose as "
    "bold simplified shapes — large foreground forms, mid-ground "
    "supporting elements, and a flat background. No empty margins, no "
    "fiddly background clutter."
)

_BACKGROUND_DEFAULT = (
    "Use a bold solid color (deep blue, black, bold red, or clean white) "
    "behind the subject and any background motifs for contrast. Never "
    "green as the dominant background."
)


def _tables(bind: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    """Create the three AI tables and seed the default prompt library."""
    bind = op.get_bind()
    existing = _tables(bind)

    if "prompt_blocks" not in existing:
        op.create_table(
            "prompt_blocks",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prompt_blocks_kind", "prompt_blocks", ["kind"])

    if "prompt_presets" not in existing:
        op.create_table(
            "prompt_presets",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("style_block_id", sa.Uuid(), sa.ForeignKey("prompt_blocks.id"), nullable=False),
            sa.Column("palette_block_id", sa.Uuid(), sa.ForeignKey("prompt_blocks.id"), nullable=False),
            sa.Column("legibility_block_id", sa.Uuid(), sa.ForeignKey("prompt_blocks.id"), nullable=False),
            sa.Column("composition_block_id", sa.Uuid(), sa.ForeignKey("prompt_blocks.id"), nullable=False),
            sa.Column("background_block_id", sa.Uuid(), sa.ForeignKey("prompt_blocks.id"), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prompt_presets_name", "prompt_presets", ["name"], unique=True)

    if "gemini_sync_jobs" not in existing:
        op.create_table(
            "gemini_sync_jobs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("target_device_id", sa.Uuid(), sa.ForeignKey("devices.id"), nullable=False),
            sa.Column("prompt_preset_id", sa.Uuid(), sa.ForeignKey("prompt_presets.id"), nullable=False),
            sa.Column("is_portrait", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("subjects", sa.JSON(), nullable=False),
            sa.Column("images_per_subject", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("retention_days", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_gemini_sync_jobs_name", "gemini_sync_jobs", ["name"], unique=True)

    _seed_defaults(bind)


def _seed_defaults(bind: sa.engine.Connection) -> None:
    """Seed default blocks + a humanoid preset if not already present."""
    existing_names = {row[0] for row in bind.execute(sa.text("SELECT name FROM prompt_blocks")).fetchall()}

    blocks: list[tuple[str, str, str, bool]] = [
        ("style", "poster_screenprint", _STYLE_DEFAULT, True),
        ("palette", "spectra_6", _PALETTE_SPECTRA_6, True),
        ("legibility", "eink_bold_shapes", _LEGIBILITY_EINK, True),
        ("composition", "humanoid_closeup", _COMPOSITION_HUMANOID, True),
        ("composition", "scene_full_frame", _COMPOSITION_SCENE, False),
        ("background", "bold_solid", _BACKGROUND_DEFAULT, True),
    ]

    ids: dict[str, str] = {}
    now = datetime.now()
    for kind, name, text, is_default in blocks:
        if name in existing_names:
            row = bind.execute(sa.text("SELECT id FROM prompt_blocks WHERE name = :n"), {"n": name}).fetchone()
            if row is not None:
                ids[name] = str(row[0])
            continue
        new_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO prompt_blocks (id, kind, name, text, is_default, created_at, updated_at) "
                "VALUES (:id, :kind, :name, :text, :is_default, :created_at, :updated_at)"
            ),
            {
                "id": new_id,
                "kind": kind,
                "name": name,
                "text": text,
                "is_default": is_default,
                "created_at": now,
                "updated_at": now,
            },
        )
        ids[name] = new_id

    preset_exists = bind.execute(
        sa.text("SELECT 1 FROM prompt_presets WHERE name = :n"), {"n": "e_ink_humanoid"}
    ).fetchone()
    if preset_exists is None:
        # Build the column list dynamically so the seed works whether the
        # ``model_name`` column already exists (fresh DB created from the
        # current SQLModel metadata) or not (older DB upgrading through 0004
        # before 0005 adds the column).
        preset_columns = {c["name"] for c in sa.inspect(bind).get_columns("prompt_presets")}
        params: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "name": "e_ink_humanoid",
            "style": ids["poster_screenprint"],
            "palette": ids["spectra_6"],
            "leg": ids["eink_bold_shapes"],
            "comp": ids["humanoid_closeup"],
            "bg": ids["bold_solid"],
            "is_default": True,
            "created_at": now,
            "updated_at": now,
        }
        columns = (
            "id, name, style_block_id, palette_block_id, legibility_block_id, "
            "composition_block_id, background_block_id, is_default, created_at, updated_at"
        )
        values = ":id, :name, :style, :palette, :leg, :comp, :bg, :is_default, :created_at, :updated_at"
        if "model_name" in preset_columns:
            columns += ", model_name"
            values += ", :model_name"
            params["model_name"] = "gemini-2.5-flash-image"
        bind.execute(
            sa.text(f"INSERT INTO prompt_presets ({columns}) VALUES ({values})"),
            params,
        )


def downgrade() -> None:
    """Drop the three AI tables (seed data goes with them)."""
    bind = op.get_bind()
    existing = _tables(bind)
    if "gemini_sync_jobs" in existing:
        op.drop_index("ix_gemini_sync_jobs_name", table_name="gemini_sync_jobs")
        op.drop_table("gemini_sync_jobs")
    if "prompt_presets" in existing:
        op.drop_index("ix_prompt_presets_name", table_name="prompt_presets")
        op.drop_table("prompt_presets")
    if "prompt_blocks" in existing:
        op.drop_index("ix_prompt_blocks_kind", table_name="prompt_blocks")
        op.drop_table("prompt_blocks")
