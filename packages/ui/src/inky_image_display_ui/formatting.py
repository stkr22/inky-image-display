"""Small formatting helpers shared by the Flet views."""

from __future__ import annotations

from datetime import datetime


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string from an API payload.

    Returns ``None`` if the input is ``None`` or cannot be parsed.
    """
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_datetime(value: str | datetime | None, fallback: str = "—") -> str:
    """Format a datetime (or ISO string) as ``YYYY-MM-DD HH:MM``.

    ``fallback`` is returned for ``None`` or unparseable input.
    """
    if value is None:
        return fallback
    dt = value if isinstance(value, datetime) else parse_datetime(value)
    if dt is None:
        return fallback
    return dt.strftime("%Y-%m-%d %H:%M")


def format_tags(tags: str | None) -> list[str]:
    """Split a comma-separated tag string into a trimmed list."""
    if not tags:
        return []
    return [t.strip() for t in tags.split(",") if t.strip()]


def join_tags(tags: list[str]) -> str | None:
    """Join a tag list back into the comma-separated wire format."""
    cleaned = [t.strip() for t in tags if t.strip()]
    return ", ".join(cleaned) if cleaned else None
