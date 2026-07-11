"""Push notifications for events nobody sees in the UI.

E-ink panels hang on walls; their operator is not watching the admin page
when one gets stuck. When ``API_NOTIFY_URL`` is configured, refresh-health
transitions are POSTed there as plain text with a ``Title`` header — the
ntfy.sh convention, deliberately minimal so a generic webhook receiver or
a curl-compatible endpoint works too.

Delivery is strictly best-effort: notifications ride on the MQTT ack path,
so they run as detached tasks and swallow every error. A broken webhook
must never delay or fail ack processing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from inky_image_display_api.config import Settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0

# Detached tasks must be referenced until done or the event loop may GC
# them mid-flight (asyncio only keeps weak references to tasks).
_pending: set[asyncio.Task[None]] = set()


def notify_in_background(settings: Settings, title: str, message: str) -> None:
    """Fire a notification without blocking or failing the caller."""
    if settings.notify_url is None:
        return
    task = asyncio.get_running_loop().create_task(_post(settings.notify_url, title, message))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _post(url: str, title: str, message: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=message.encode(), headers={"Title": title})
            response.raise_for_status()
    except Exception:
        # Best-effort by design; the interesting event is already in the DB
        # and the UI. Log so a misconfigured URL is discoverable.
        logger.warning("Failed to deliver notification %r", title, exc_info=True)
