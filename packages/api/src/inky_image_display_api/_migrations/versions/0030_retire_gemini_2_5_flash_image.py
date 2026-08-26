"""Move prompt presets off the retiring gemini-2.5-flash-image model.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-26

``gemini-2.5-flash-image`` still answers, but Google retires it on 2026-10-02,
at which point every preset still naming it stops generating. Moving presets now
means the cutover is a no-op rather than a morning of blank panels.

The replacement is the same tier (flash, not flash-lite), so image quality is
not quietly traded for cost. It does cost more per image — roughly $0.067
against $0.039 at 1K — which for a handful of images a day is cents, and
flash-lite at $0.034 is there if that ever stops being true.

Only rows still carrying the old default are moved; a model an operator chose
in the UI is left alone, even if it is the retiring one. The bookshelf presets
seeded by 0028 name gemini-3-pro-image and are untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_RETIRING = "gemini-2.5-flash-image"
_REPLACEMENT = "gemini-3.1-flash-image"

_UPDATE = sa.text("UPDATE prompt_presets SET model_name = :new, updated_at = :now WHERE model_name = :old")


def upgrade() -> None:
    """Repoint presets still on the retiring default."""
    op.get_bind().execute(
        _UPDATE,
        {"new": _REPLACEMENT, "old": _RETIRING, "now": datetime.now(UTC).replace(tzinfo=None)},
    )


def downgrade() -> None:
    """Put the retiring model back on presets that carry the replacement."""
    op.get_bind().execute(
        _UPDATE,
        {"new": _RETIRING, "old": _REPLACEMENT, "now": datetime.now(UTC).replace(tzinfo=None)},
    )
