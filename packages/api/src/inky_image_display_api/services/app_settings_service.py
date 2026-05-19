"""Read/write helpers for operator-tunable app settings.

Values live in the ``app_settings`` key/value table as JSON-encoded
scalars. When a row is absent we fall back to the env-loaded
``Settings`` value so a fresh deployment keeps working without any
manual seeding.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from inky_image_display_shared.models import AppSetting
from inky_image_display_shared.time import utcnow
from sqlmodel import select

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from inky_image_display_api.config import Settings

# Min/max mirror the ``RefreshIntervalSeconds`` constraint in schemas.py
# so values written via the UI route can never violate what we accept
# from the per-device dialog.
_MIN_REFRESH_SECONDS = 1
_MAX_REFRESH_SECONDS = 7 * 24 * 3600

DEFAULT_REFRESH_SECONDS_KEY = "default_refresh_seconds"


async def get_default_refresh_seconds(session: AsyncSession, settings: Settings) -> int:
    """Return the configured default refresh interval in seconds.

    Falls back to ``settings.default_display_duration`` when the row is
    missing or its value is unparseable, so a broken row can't take the
    rotation system offline.
    """
    row = await _get(session, DEFAULT_REFRESH_SECONDS_KEY)
    if row is None:
        return settings.default_display_duration
    try:
        value = json.loads(row.value)
    except json.JSONDecodeError:
        return settings.default_display_duration
    if isinstance(value, int) and _MIN_REFRESH_SECONDS <= value <= _MAX_REFRESH_SECONDS:
        return value
    return settings.default_display_duration


async def set_default_refresh_seconds(session: AsyncSession, seconds: int) -> int:
    """Persist a new default refresh interval; returns the stored value."""
    if not _MIN_REFRESH_SECONDS <= seconds <= _MAX_REFRESH_SECONDS:
        raise ValueError(f"seconds must be between {_MIN_REFRESH_SECONDS} and {_MAX_REFRESH_SECONDS}")
    encoded = json.dumps(seconds)
    row = await _get(session, DEFAULT_REFRESH_SECONDS_KEY)
    if row is None:
        row = AppSetting(key=DEFAULT_REFRESH_SECONDS_KEY, value=encoded, updated_at=utcnow())
        session.add(row)
    else:
        row.value = encoded
        row.updated_at = utcnow()
        session.add(row)
    await session.commit()
    return seconds


async def _get(session: AsyncSession, key: str) -> AppSetting | None:
    result = await session.exec(select(AppSetting).where(AppSetting.key == key))
    return result.first()
