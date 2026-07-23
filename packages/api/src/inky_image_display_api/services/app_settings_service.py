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
STAGGER_ROTATION_KEY = "stagger_rotation"


async def get_stagger_rotation(session: AsyncSession) -> bool:
    """Whether mass rotations spread the panels' next refreshes.

    Applies after a grid release or the end of quiet hours: instead of
    leaving simultaneously rotated panels in lockstep, their next
    refreshes are spread evenly across the interval. Defaults to enabled;
    a broken row can't disable it.
    """
    row = await _get(session, STAGGER_ROTATION_KEY)
    if row is None:
        return True
    try:
        return json.loads(row.value) is not False
    except json.JSONDecodeError:
        return True


async def set_stagger_rotation(session: AsyncSession, enabled: bool) -> bool:
    """Persist the stagger-rotation flag; returns the stored value."""
    await _upsert(session, STAGGER_ROTATION_KEY, json.dumps(enabled))
    return enabled


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
    await _upsert(session, DEFAULT_REFRESH_SECONDS_KEY, json.dumps(seconds))
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
    await _upsert(session, QUIET_HOURS_KEY, quiet_hours.model_dump_json())
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


async def _upsert(session: AsyncSession, key: str, encoded: str) -> None:
    row = await _get(session, key)
    if row is None:
        row = AppSetting(key=key, value=encoded, updated_at=utcnow())
    else:
        row.value = encoded
        row.updated_at = utcnow()
    session.add(row)
    await session.commit()
