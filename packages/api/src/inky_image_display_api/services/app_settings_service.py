"""Read/write helpers for operator-tunable app settings.

Values live in the ``app_settings`` key/value table as JSON-encoded
scalars. When a row is absent we fall back to the env-loaded
``Settings`` value so a fresh deployment keeps working without any
manual seeding.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from inky_image_display_shared.models import AppSetting
from inky_image_display_shared.schemas.responses import QuietHoursSettings
from inky_image_display_shared.time import as_utc_aware, utcnow
from pydantic import ValidationError
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
QUIET_HOURS_KEY = "quiet_hours"


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


async def get_quiet_hours(session: AsyncSession) -> QuietHoursSettings:
    """Return the configured quiet-hours window.

    Missing or unparseable rows fall back to the disabled default so a
    broken setting can never silently pause (or unpause) the fleet.
    """
    row = await _get(session, QUIET_HOURS_KEY)
    if row is None:
        return QuietHoursSettings()
    try:
        return QuietHoursSettings.model_validate_json(row.value)
    except ValidationError:
        return QuietHoursSettings()


async def set_quiet_hours(session: AsyncSession, quiet_hours: QuietHoursSettings) -> QuietHoursSettings:
    """Persist the quiet-hours window; returns the stored value."""
    encoded = quiet_hours.model_dump_json()
    row = await _get(session, QUIET_HOURS_KEY)
    if row is None:
        row = AppSetting(key=QUIET_HOURS_KEY, value=encoded, updated_at=utcnow())
    else:
        row.value = encoded
        row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    return quiet_hours


def is_quiet_now(quiet_hours: QuietHoursSettings, now: datetime) -> bool:
    """Whether ``now`` (UTC) falls inside the configured quiet window.

    The window is evaluated in the configured timezone so "22:00-07:00"
    means wall-clock night wherever the panels hang, including across a
    DST change. A window that wraps midnight (start > end) covers
    [start, 24:00) plus [00:00, end); start == end is treated as disabled
    rather than a 24-hour window, since an always-quiet fleet is far more
    likely a misconfiguration than an intent.
    """
    if not quiet_hours.enabled:
        return False
    start = time.fromisoformat(quiet_hours.start)
    end = time.fromisoformat(quiet_hours.end)
    if start == end:
        return False
    local_now = as_utc_aware(now).astimezone(ZoneInfo(quiet_hours.timezone)).time()
    if start < end:
        return start <= local_now < end
    return local_now >= start or local_now < end


async def _get(session: AsyncSession, key: str) -> AppSetting | None:
    result = await session.exec(select(AppSetting).where(AppSetting.key == key))
    return result.first()
