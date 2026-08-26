"""Move display jobs off the retired gemini-2.5-flash text model.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-26

``gemini-2.5-flash`` is refused for API keys issued after its retirement — the
API answers 404 with "no longer available to new users" and names
``gemini-3.6-flash`` as the replacement. Existing keys still work, so a
deployment can be running happily while a new one cannot generate a story at
all, and rotating the key would break MOTD with no obvious cause.

Only rows still carrying the old default are moved: a model an operator chose
in the UI is left alone, even if it is the retired one, because overriding a
deliberate choice is worse than the 404 it would avoid.

The image model is untouched — ``gemini-2.5-flash-image`` still answers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_RETIRED = "gemini-2.5-flash"
_REPLACEMENT = "gemini-3.6-flash"

_UPDATE = sa.text("UPDATE display_jobs SET text_model_name = :new, updated_at = :now WHERE text_model_name = :old")


def upgrade() -> None:
    """Repoint display jobs still on the retired default."""
    op.get_bind().execute(
        _UPDATE,
        {"new": _REPLACEMENT, "old": _RETIRED, "now": datetime.now(UTC).replace(tzinfo=None)},
    )


def downgrade() -> None:
    """Put the retired model back on rows that carry the replacement."""
    op.get_bind().execute(
        _UPDATE,
        {"new": _RETIRED, "old": _REPLACEMENT, "now": datetime.now(UTC).replace(tzinfo=None)},
    )
