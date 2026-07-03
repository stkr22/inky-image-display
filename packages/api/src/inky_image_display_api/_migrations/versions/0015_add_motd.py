"""Add message-of-the-day tables, tune prompt defaults, seed the scene preset.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-02

Ships the MOTD feature in one step:

- New tables: a singleton-style config (generation prompt, schedule,
  duration, live session state), per-device part assignments, the generated
  messages and their pre-rendered per-panel screens, plus a
  ``claimed_by_motd_config_id`` claim column on ``devices`` mirroring the
  existing grid claim so an active MOTD takes devices out of solo rotation.

- Prompt-default tuning, validated with side-by-side Gemini renders: the
  style block's "expressive energy of a Van Gogh oil" leaked into *content*
  (Van Gogh painted as the story's protagonist; Starry Night mannerisms in
  scenes), so it now names only the painterly qualities. The legibility
  block gains a hard no-text rule (generated captions dither badly and
  misspell). ``scene_full_frame`` becomes a generic hero-subject composition
  for objects, places and abstract ideas. That phrasing consistently trips
  Gemini's refusal for *named real people* (0/10 in testing), so
  ``humanoid_closeup`` — which passes with named people — stays the default
  block for portraits. Retunes follow the 0013 mechanism: only rows still
  carrying the previous seed text are touched, so operator edits survive.

- Seeds an ``e_ink_scene`` preset (identical to ``e_ink_humanoid`` except
  the scene composition); new MOTD configs default to it by name because
  MOTD image subjects are scene descriptions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create MOTD schema, retune prompt defaults, seed the scene preset."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "motd_configs" not in tables:
        op.create_table(
            "motd_configs",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("content_prompt", sa.String(), nullable=False),
            sa.Column("source_mode", sa.String(), nullable=False),
            sa.Column(
                "image_preset_id",
                sa.Uuid(),
                sa.ForeignKey("prompt_presets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("text_model_name", sa.String(), nullable=False),
            sa.Column("schedule_enabled", sa.Boolean(), nullable=False),
            sa.Column("display_time", sa.String(), nullable=False),
            sa.Column("weekday_mask", sa.Integer(), nullable=False),
            sa.Column("timezone", sa.String(), nullable=False),
            sa.Column("generation_lead_minutes", sa.Integer(), nullable=False),
            sa.Column("display_duration_seconds", sa.Integer(), nullable=True),
            sa.Column("active_message_id", sa.Uuid(), nullable=True),
            sa.Column("active_since", sa.DateTime(), nullable=True),
            sa.Column("active_expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_generated_on", sa.Date(), nullable=True),
            sa.Column("last_displayed_on", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "motd_device_assignments" not in tables:
        op.create_table(
            "motd_device_assignments",
            sa.Column(
                "config_id",
                sa.Uuid(),
                sa.ForeignKey("motd_configs.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "device_id",
                sa.Uuid(),
                sa.ForeignKey("devices.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column("parts", sa.String(), nullable=False),
            sa.Column("rotation_index", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if "motd_messages" not in tables:
        op.create_table(
            "motd_messages",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "config_id",
                sa.Uuid(),
                sa.ForeignKey("motd_configs.id", ondelete="CASCADE"),
                nullable=False,
            ),
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
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if "motd_screens" not in tables:
        op.create_table(
            "motd_screens",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "message_id",
                sa.Uuid(),
                sa.ForeignKey("motd_messages.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("part", sa.String(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("is_portrait", sa.Boolean(), nullable=False),
            sa.Column("storage_path", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if "devices" in tables:
        existing = {c["name"] for c in inspector.get_columns("devices")}
        if "claimed_by_motd_config_id" not in existing:
            with op.batch_alter_table("devices") as batch:
                batch.add_column(sa.Column("claimed_by_motd_config_id", sa.Uuid(), nullable=True))
                batch.create_foreign_key(
                    "fk_devices_claimed_by_motd_config_id_motd_configs",
                    "motd_configs",
                    ["claimed_by_motd_config_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    _retune_default_blocks(bind)
    _seed_scene_preset(bind)


def downgrade() -> None:
    """One-way migration."""
    return


# --- Prompt-default tuning ------------------------------------------------------

# 0013 text (the guard: only retune rows still matching).

_OLD_STYLE = (
    "Bold painterly illustration with the expressive energy of a Van Gogh oil: "
    "confident visible brushwork, impasto texture, and dramatic light-to-shadow "
    "modelling that gives every form real depth and volume. High contrast and "
    "rich, saturated colour. Build the image from strong, well-separated shapes "
    "with a clear focal subject — but do NOT flatten them: let colour shade, "
    "blend and turn across each surface. Stylised and expressive, not "
    "photorealistic — closer to a striking gallery art print than a minimal "
    "flat poster."
)
_OLD_LEGIBILITY = (
    "Target medium is a high-resolution 6-colour e-ink panel that dithers "
    "smoothly, so tonal shading, surface texture and moderate detail reproduce "
    "well — keep them, don't strip them out. Build on clear, well-separated "
    "forms with crisp high-contrast edges so the subject reads instantly from "
    "across a room. Avoid only the failure modes: hair-thin lines, tiny "
    "cluttered filigree, and broad low-contrast passages of similar mid-tones "
    "that would turn to mush."
)
_OLD_COMPOSITION_SCENE = (
    "Full-frame scene composition: {subject} occupies the central focus with "
    "surrounding context filling the frame edge to edge. Compose with bold, "
    "well-separated forms — large foreground elements, supporting mid-ground, "
    "and a simpler background that still carries its own depth and atmosphere. "
    "No empty margins, no fiddly background clutter."
)

_NEW_STYLE = (
    "Bold painterly illustration: confident visible brushwork, thick expressive "
    "strokes, and dramatic light-to-shadow modelling that gives every form real "
    "depth and volume. High contrast and rich, saturated colour. Build the "
    "image from strong, well-separated shapes with a clear focal subject — but "
    "do NOT flatten them: let colour shade, blend and turn across each surface. "
    "Stylised and expressive, not photorealistic — closer to a striking gallery "
    "art print than a minimal flat poster."
)
_NEW_LEGIBILITY = (
    _OLD_LEGIBILITY
    + " Render no text of any kind: no words, lettering, numbers, labels or logos anywhere in the image."
)
_NEW_COMPOSITION_SCENE = (
    "One unmistakable focal subject: {subject}. If it is a person or creature, "
    "frame them large and close. If it is an object or place, let it dominate "
    "the frame as the hero. If it is an idea or event, depict one concrete, "
    "emblematic moment or object that stands for it — never a diagram or "
    "collage. The focal subject fills most of the frame edge to edge with no "
    "empty margins, supported by at most one or two large, bold secondary "
    "shapes; no fiddly detail."
)

# Each tuple is: block kind, block name, 0013 text, tuned text.
_RETUNES: list[tuple[str, str, str, str]] = [
    ("style", "poster_screenprint", _OLD_STYLE, _NEW_STYLE),
    ("legibility", "eink_bold_shapes", _OLD_LEGIBILITY, _NEW_LEGIBILITY),
    ("composition", "scene_full_frame", _OLD_COMPOSITION_SCENE, _NEW_COMPOSITION_SCENE),
]

_UPDATE = sa.text(
    "UPDATE prompt_blocks SET text = :new, updated_at = :now WHERE kind = :kind AND name = :name AND text = :old"
)


def _retune_default_blocks(bind: sa.engine.Connection) -> None:
    """Apply each retune only if the row still carries the previous seed text."""
    now = datetime.now(UTC).replace(tzinfo=None)
    for kind, name, from_text, to_text in _RETUNES:
        bind.execute(_UPDATE, {"new": to_text, "now": now, "kind": kind, "name": name, "old": from_text})


# --- Scene preset seed ----------------------------------------------------------

_PRESET_NAME = "e_ink_scene"

_BLOCK_NAMES = {
    "style_block_id": "poster_screenprint",
    "palette_block_id": "spectra_6",
    "legibility_block_id": "eink_bold_shapes",
    "composition_block_id": "scene_full_frame",
    "background_block_id": "bold_solid",
}

_PRESETS_TBL = sa.Table(
    "prompt_presets",
    sa.MetaData(),
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("name", sa.String()),
    sa.Column("style_block_id", sa.Uuid()),
    sa.Column("palette_block_id", sa.Uuid()),
    sa.Column("legibility_block_id", sa.Uuid()),
    sa.Column("composition_block_id", sa.Uuid()),
    sa.Column("background_block_id", sa.Uuid()),
    sa.Column("model_name", sa.String()),
    sa.Column("is_default", sa.Boolean()),
    sa.Column("created_at", sa.DateTime()),
    sa.Column("updated_at", sa.DateTime()),
)


def _coerce_uuid(value: object) -> uuid.UUID:
    """Parse a UUID column value regardless of stored string format."""
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, bytes):
        return uuid.UUID(bytes=value)
    return uuid.UUID(str(value))


def _seed_scene_preset(bind: sa.engine.Connection) -> None:
    """Insert the scene preset once; skip if present or blocks were deleted."""
    row = bind.execute(sa.text("SELECT 1 FROM prompt_presets WHERE name = :n"), {"n": _PRESET_NAME}).fetchone()
    if row is not None:
        return

    blocks: dict[str, uuid.UUID] = {}
    for column, block_name in _BLOCK_NAMES.items():
        found = bind.execute(sa.text("SELECT id FROM prompt_blocks WHERE name = :n"), {"n": block_name}).fetchone()
        if found is None:
            # Operator removed a seeded block; don't guess a replacement.
            return
        blocks[column] = _coerce_uuid(found[0])

    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        _PRESETS_TBL,
        [
            {
                "id": uuid.uuid4(),
                "name": _PRESET_NAME,
                **blocks,
                "model_name": "gemini-2.5-flash-image",
                "is_default": False,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
