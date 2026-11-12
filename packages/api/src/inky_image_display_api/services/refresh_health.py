"""Shared gate deciding whether a device may receive automatic image pushes.

A device that acked a failed refresh is skipped by every automatic dispatch
path (solo rotation, grids, MOTD, GenAI) so the scheduler doesn't pile images
onto a stuck panel. Recovery normally comes from the controller's own retry
loop, whose success ack clears ``last_refresh_ok`` — but that loop lives only
in the controller's memory. A controller restart (notably the physical power
cycle that recovers a latched EL133UF1 panel) or a success ack lost to an MQTT
outage would otherwise halt the device permanently, with nothing left on
either side to break the deadlock (see docs/refresh-issues.md).

The gate therefore expires: a failure older than the configured backoff no
longer blocks dispatch, and the next push settles the device's real state —
success clears the flag, failure re-arms the backoff with a fresh timestamp.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from inky_image_display_shared.models import Device
from sqlalchemy import and_, or_
from sqlmodel import col

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement


def dispatch_allowed_clause(now: datetime, backoff_seconds: int) -> ColumnElement[bool]:
    """Build a SQL filter matching devices NOT blocked by a recent failed refresh.

    A device is blocked only while all three hold: the last refresh failed,
    an error timestamp was recorded, and that timestamp is within the
    backoff window. A ``NULL`` ``last_refresh_ok`` (never acked) or ``NULL``
    ``last_error_at`` (shouldn't occur — acks record both together) stays
    eligible so an anomalous row can never deadlock a device.
    """
    cutoff = now - timedelta(seconds=backoff_seconds)
    return or_(
        col(Device.last_refresh_ok).is_not(False),
        col(Device.last_error_at).is_(None),
        col(Device.last_error_at) <= cutoff,
    )


def is_dispatch_blocked(device: Device, now: datetime, backoff_seconds: int) -> bool:
    """In-memory equivalent of :func:`dispatch_allowed_clause` (inverted)."""
    if device.last_refresh_ok is not False or device.last_error_at is None:
        return False
    return device.last_error_at > now - timedelta(seconds=backoff_seconds)


def auto_dispatch_clause(now: datetime, backoff_seconds: int) -> ColumnElement[bool]:
    """Devices any automatic push (solo rotation, GenAI) may target.

    One predicate for every automatic path so they can't drift: a pinned
    panel keeps its image until the operator unpins it, and a grid-claimed
    panel belongs to its grid until released — pushing to either would
    silently undo an operator decision.
    """
    return and_(
        col(Device.is_online).is_(True),
        col(Device.is_pinned).is_(False),
        col(Device.claimed_by_grid_id).is_(None),
        dispatch_allowed_clause(now, backoff_seconds),
    )
