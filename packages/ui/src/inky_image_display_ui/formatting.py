"""Small formatting helpers shared by the views."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string from an API payload.

    The API emits offset-aware UTC strings (e.g. ``...+00:00``). For
    backwards compatibility with older payloads we treat naive strings
    as UTC.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def format_datetime(value: str | datetime | None, fallback: str = "—") -> str:
    """Format a datetime in the host OS's local timezone.

    Output looks like ``2026-05-17 15:34 CEST``. The trailing ``%Z`` makes
    the timezone explicit so users on the wrong machine notice immediately
    instead of silently misreading UTC times as local.
    """
    if value is None:
        return fallback
    dt = value if isinstance(value, datetime) else parse_datetime(value)
    if dt is None:
        return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    local = dt.astimezone()
    suffix = local.strftime("%Z") or ""
    base = local.strftime("%Y-%m-%d %H:%M")
    return f"{base} {suffix}".rstrip()


def format_relative(value: str | datetime | None, *, now: datetime | None = None, fallback: str = "—") -> str:
    """Human-friendly relative time like ``in 4m`` or ``5m ago``.

    Past times read ``"… ago"`` and future times read ``"in …"``; the
    boundary uses a 30-second window to render as ``"due now"`` so the
    upcoming-queue dashboard doesn't flicker between past/future as the
    rotation tick fires.
    """
    if value is None:
        return fallback
    dt = value if isinstance(value, datetime) else parse_datetime(value)
    if dt is None:
        return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    delta = (dt - reference).total_seconds()
    if abs(delta) < _DUE_NOW_WINDOW_SECONDS:
        return "due now"
    magnitude = abs(int(delta))
    text = _humanize_seconds(magnitude)
    return f"in {text}" if delta > 0 else f"{text} ago"


_DUE_NOW_WINDOW_SECONDS = 30
_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24


def _humanize_seconds(seconds: int) -> str:
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds}s"
    minutes = seconds // _SECONDS_PER_MINUTE
    if minutes < _MINUTES_PER_HOUR:
        return f"{minutes}m"
    hours = minutes // _MINUTES_PER_HOUR
    remaining_minutes = minutes % _MINUTES_PER_HOUR
    if hours < _HOURS_PER_DAY:
        return f"{hours}h" if remaining_minutes == 0 else f"{hours}h {remaining_minutes}m"
    days = hours // _HOURS_PER_DAY
    remaining_hours = hours % _HOURS_PER_DAY
    return f"{days}d" if remaining_hours == 0 else f"{days}d {remaining_hours}h"


def format_interval_seconds(value: int | None, *, default_label: str = "default") -> str:
    """Render a ``refresh_interval_seconds`` value as a short human string."""
    if value is None:
        return default_label
    return _humanize_seconds(int(value))


def split_hours_minutes(seconds: int | None) -> tuple[int, int]:
    """Split a seconds value into ``(hours, minutes)`` for the editor inputs.

    Returns ``(0, 0)`` for ``None`` so the editor starts blank when an
    entity has no override set.
    """
    if not seconds or seconds < 0:
        return 0, 0
    minutes_total = seconds // 60
    return minutes_total // 60, minutes_total % 60


def format_tags(tags: str | None) -> list[str]:
    """Split a comma-separated tag string into a trimmed list."""
    if not tags:
        return []
    return [t.strip() for t in tags.split(",") if t.strip()]


def join_tags(tags: list[str]) -> str | None:
    """Join a tag list back into the comma-separated wire format."""
    cleaned = [t.strip() for t in tags if t.strip()]
    return ", ".join(cleaned) if cleaned else None
