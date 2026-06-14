"""Tests for the controller's failed-refresh retry loop.

When a display refresh fails the API stops auto-rotating the device, so the
controller must re-attempt the same image on a cadence until it succeeds — the
success ack is what clears the error server-side. A superseding command (e.g. a
manual resend) must cancel any in-flight retry.
"""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from inky_image_display_controller.config import Settings
from inky_image_display_controller.controller import DisplayController
from inky_image_display_controller.exceptions import DisplayError
from inky_image_display_shared.schemas import DisplayCommand
from PIL import Image


@dataclass
class Harness:
    """A controller wired to mocks, with handles to the two mocks tests drive."""

    controller: DisplayController
    show: AsyncMock  # _display.show_image
    ack: AsyncMock  # _mqtt.publish_ack

    def ack_successes(self) -> list[bool]:
        """successful_display_change of every ack the controller published."""
        return [call.args[0].successful_display_change for call in self.ack.call_args_list]


def _make_harness(retry_interval: float = 0.01) -> Harness:
    """Build a controller with mocked S3/MQTT/display and a fast retry cadence."""
    settings = Settings()
    settings.display.mock = True  # create_display() returns a MockDisplay, no hardware
    controller = DisplayController(settings)
    # Bypass the ge=10 validation floor — tests must not really sleep minutes.
    controller._settings.display.retry_interval_seconds = retry_interval  # ty: ignore[invalid-assignment]
    controller._s3 = MagicMock(is_configured=True, fetch_image=AsyncMock(return_value=Image.new("RGB", (1600, 1200))))
    show = AsyncMock()
    ack = AsyncMock()
    controller._display = MagicMock(show_image=show)
    controller._mqtt = MagicMock(publish_ack=ack)
    return Harness(controller=controller, show=show, ack=ack)


def _display_command(image_id: str = "img-1", path: str = "some/key.jpg") -> DisplayCommand:
    return DisplayCommand(action="display", image_path=path, image_id=image_id)


@pytest.mark.asyncio
async def test_failed_display_acks_failure_and_schedules_retry() -> None:
    h = _make_harness()
    h.show.side_effect = DisplayError("stuck")

    await h.controller._handle_command(_display_command())

    # The failure is acked so the API can back off, and a retry is queued.
    assert h.ack_successes() == [False]
    assert h.controller._retry_task is not None
    h.controller._cancel_retry()


@pytest.mark.asyncio
async def test_retry_eventually_succeeds_and_stops() -> None:
    h = _make_harness()
    # First attempt (in _handle_command) stalls, the retry attempt succeeds.
    h.show.side_effect = [DisplayError("stuck"), None]

    await h.controller._handle_command(_display_command())
    assert h.controller._retry_task is not None
    await asyncio.wait_for(h.controller._retry_task, timeout=2.0)

    # One failure ack, then one success ack — the success ends the loop.
    assert h.ack_successes() == [False, True]
    assert h.controller._current_image_id == "img-1"


@pytest.mark.asyncio
async def test_new_command_cancels_pending_retry() -> None:
    h = _make_harness(retry_interval=30.0)  # long enough that it can't fire on its own
    h.show.side_effect = DisplayError("stuck")

    await h.controller._handle_command(_display_command())
    pending = h.controller._retry_task
    assert pending is not None and not pending.done()

    # A fresh, succeeding command supersedes the retry.
    h.show.side_effect = None
    await h.controller._handle_command(_display_command(image_id="img-2", path="other.jpg"))

    # cancel() only requests cancellation; awaiting drains it to the cancelled state.
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert pending.cancelled()
    assert h.ack_successes() == [False, True]


@pytest.mark.asyncio
async def test_shutdown_stops_retry_loop_cleanly() -> None:
    h = _make_harness(retry_interval=30.0)
    h.show.side_effect = DisplayError("stuck")

    await h.controller._handle_command(_display_command())
    task = h.controller._retry_task
    assert task is not None

    h.controller._shutdown_event.set()
    task.cancel()  # mirrors _cleanup()/supersession; loop must exit cleanly
    with pytest.raises(asyncio.CancelledError):
        await task
