"""Time helpers enforcing a UTC invariant across services.

SQLite stores ``DateTime`` columns as naive ISO text and does not honour
``DateTime(timezone=True)``, so we keep stored columns naive but route all
writers through :func:`utcnow` and attach ``tzinfo=UTC`` at API response
boundaries. That keeps the schema unchanged while making "stored values
are UTC" a single-point invariant.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC time as a *naive* datetime.

    Matches the naive-UTC convention of existing ``DateTime`` columns so
    callers can use this anywhere ``datetime.now()`` was used previously.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc_aware(value: datetime) -> datetime:
    """Attach ``tzinfo=UTC`` to a naive datetime (no shift).

    Stored values are naive-UTC by convention; this lifts them into
    offset-aware form for serialisation so clients receive
    ``2026-05-17T14:00:00+00:00`` rather than an ambiguous string.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
