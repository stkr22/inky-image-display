"""Display abstraction layer for Inky e-paper displays."""

import asyncio
import logging
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PIL import Image

from inky_image_display_controller.exceptions import DisplayError

logger = logging.getLogger(__name__)

# A stalled refresh never raises from the Inky driver, and the two supported
# panel families fail differently — so the controller watches for both:
#
#  * UC8159 (4-7.3"): _busy_wait() emits warnings.warn("... timed out ...") and
#    returns once BUSY fails to clear within its timeout. We capture that
#    warning (it otherwise goes to stderr, never reaching the logs).
#  * EL133UF1 (13.3"): _busy_wait() is SILENT — it time.sleep()s a fixed
#    duration and returns, so a refresh that never ran is indistinguishable from
#    a good one by warnings alone. We instead watch the BUSY GPIO directly (see
#    _run_show_once): per the Inky driver's own _busy_wait (which loops while the
#    line reads Value.ACTIVE), BUSY is ACTIVE (high) while the panel refreshes
#    and INACTIVE (low) when idle. A healthy refresh drives BUSY active then
#    inactive; if it never goes active the panel executed no waveform.
#
# Either way show() returns as if it succeeded, so without these checks the
# controller would ack a refresh that never physically happened
# (docs/refresh-issues.md). Recovery leans on a property of the driver:
# show() -> _update() -> setup(), and setup() issues a full RST_N hardware reset
# on EVERY call (the reset is outside its _gpio_setup guard). So simply
# re-running show() resets the panel and retries the waveform from a clean
# state — no private-state poking needed.
DEFAULT_MAX_REFRESH_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_S = 2.0
# How often to sample the BUSY GPIO while a refresh runs. A real refresh holds
# BUSY low for seconds, so 100 ms comfortably catches the transition.
DEFAULT_BUSY_POLL_INTERVAL_S = 0.1


def _busy_is_asserted(value: object) -> bool | None:
    """Interpret a gpiod line value for the panel's BUSY pin.

    Returns True when the panel is asserting BUSY (refresh running), False when
    idle/ready, or None when the value can't be interpreted. The Inky 2.x
    drivers define the polarity: ``_busy_wait`` loops *while*
    ``get_value() == Value.ACTIVE``, so **ACTIVE (high) = busy** and
    **INACTIVE (low) = idle**. Verified on EL133UF1 hardware — the line reads
    ACTIVE for the duration of ``show()`` and INACTIVE once the refresh
    completes. (An earlier active-low assumption here inverted this and made
    every healthy refresh look stalled.) We match the gpiod ``Value`` enum by
    ``name`` so this module need not import gpiod (it isn't installed off-device)
    and tests can pass a stand-in; plain bools/ints follow the same mapping
    (True/1/high = busy).
    """
    name = getattr(value, "name", None)
    if isinstance(name, str):
        upper = name.upper()
        if upper in {"ACTIVE", "HIGH"}:
            return True
        if upper in {"INACTIVE", "LOW"}:
            return False
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return None


def _classify_refresh(*, timed_out: bool, busy_observed: bool, went_busy: bool, still_busy: bool | None) -> str | None:
    """Decide whether one refresh attempt failed, returning a reason or None.

    Pure (no I/O) so the stall logic can be unit-tested without hardware.
    ``None`` means the refresh looks healthy; a string is the operator-facing
    failure reason carried into the retry loop and the device-health ack.

    This cannot detect a *partial* refresh (e.g. the 13.3 updating only one of
    its two halves): BUSY cycles normally in that case and the fault is
    downstream of any signal the host can observe.
    """
    if timed_out:
        return "e-paper BUSY signal never cleared (driver reported a busy-wait timeout)"
    if busy_observed and not went_busy:
        return "panel never asserted BUSY during the refresh — no waveform ran"
    if still_busy is True:
        return "BUSY still asserted after show() returned — refresh stalled mid-update"
    return None


# Maps the panel dimensions reported by the Inky library (always
# landscape-native, longer dim first) to the device-profile key seeded
# in API migration 0007. The controller no longer sends raw dimensions
# to the API — it sends the profile key, and the API resolves the rest.
_PANEL_DIMS_TO_PROFILE_KEY: dict[tuple[int, int], str] = {
    (640, 400): "inky_impression_4_spectra6",
    (800, 480): "inky_impression_7_spectra6",
    (1600, 1200): "inky_impression_13_spectra6",
}

# Reverse: profile key -> (width, height). Used by the mock display so
# tests configure a panel by name and get the matching dimensions.
_PROFILE_KEY_TO_PANEL_DIMS: dict[str, tuple[int, int]] = {key: dims for dims, key in _PANEL_DIMS_TO_PROFILE_KEY.items()}


def profile_key_for_panel(width: int, height: int) -> str:
    """Look up the seeded device-profile key for a detected panel size.

    Raises:
        DisplayError: If the (width, height) doesn't match a seeded profile.
            Treated as fatal so registration fails fast rather than silently
            misregistering against the wrong profile.

    """
    key = _PANEL_DIMS_TO_PROFILE_KEY.get((width, height))
    if key is None:
        raise DisplayError(
            f"Unsupported panel size {width}x{height}: no matching device profile. "
            f"Known sizes: {sorted(_PANEL_DIMS_TO_PROFILE_KEY)}"
        )
    return key


def panel_dims_for_profile_key(key: str) -> tuple[int, int]:
    """Look up panel (width, height) for a profile key (used by MockDisplay)."""
    dims = _PROFILE_KEY_TO_PANEL_DIMS.get(key)
    if dims is None:
        raise DisplayError(f"Unknown device profile key '{key}'. Known keys: {sorted(_PROFILE_KEY_TO_PANEL_DIMS)}")
    return dims


class InkyDisplay:
    """Wrapper for Pimoroni Inky e-paper displays.

    The display refresh is a blocking operation (~20-25 seconds),
    so it runs in a dedicated thread pool to avoid blocking the async loop.

    Dimensions are auto-detected from the hardware during initialization.
    The Inky library itself handles any internal rotation required by the
    physical mounting — the public API always expects landscape images
    (wider than tall).

    A stalled refresh (BUSY never clears) is detected and retried with a
    hardware reset between attempts; see the module docstring constants.
    """

    def __init__(
        self,
        executor: ThreadPoolExecutor | None = None,
        *,
        max_refresh_attempts: int = DEFAULT_MAX_REFRESH_ATTEMPTS,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
        busy_poll_interval_s: float = DEFAULT_BUSY_POLL_INTERVAL_S,
        _display: Any = None,
    ) -> None:
        """Initialize the Inky display wrapper.

        Connects to hardware immediately to detect display dimensions.

        Args:
            executor: Optional thread pool executor for display operations.
            max_refresh_attempts: How many times to drive a single refresh
                before giving up. Each retry re-runs the driver's setup(),
                which issues a full RST_N hardware reset first.
            retry_delay_s: Seconds to wait between refresh attempts.
            busy_poll_interval_s: How often to sample the BUSY GPIO while a
                refresh runs (stall detection on panels that don't warn).
            _display: Pre-built Inky panel object, injected by tests so the
                retry/detection logic can be exercised without hardware.

        Raises:
            DisplayError: If the display cannot be initialized.

        """
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="inky")
        self._lock = asyncio.Lock()
        self._max_refresh_attempts = max_refresh_attempts
        self._retry_delay_s = retry_delay_s
        self._busy_poll_interval_s = busy_poll_interval_s

        # Eager init - get dimensions from hardware
        try:
            if _display is None:
                from inky.auto import auto  # noqa: PLC0415  # ty: ignore[unresolved-import]

                _display = auto()
            self._display: Any = _display
            self._width: int = self._display.width
            self._height: int = self._display.height
            logger.info("Inky display initialized: %dx%d", self._width, self._height)
        except Exception as e:
            logger.exception("Failed to initialize Inky display")
            raise DisplayError(f"Failed to initialize display: {e}") from e

    @property
    def width(self) -> int:
        """Display width in pixels (hardware landscape dimension)."""
        return self._width

    @property
    def height(self) -> int:
        """Display height in pixels (hardware landscape dimension)."""
        return self._height

    async def show_image(self, image: Image.Image, saturation: float = 0.5) -> None:
        """Display an image on the Inky screen.

        Runs the blocking display update in a thread pool.

        Args:
            image: PIL Image to display.
            saturation: Color saturation (0.0-1.0).

        Raises:
            DisplayError: If the display update fails.

        """
        async with self._lock:
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(
                    self._executor,
                    self._show_image_sync,
                    image,
                    saturation,
                )
            except DisplayError:
                raise
            except Exception as e:
                logger.exception("Failed to update display")
                raise DisplayError(f"Display update failed: {e}") from e

    def _show_image_sync(self, image: Image.Image, saturation: float) -> None:
        """Perform synchronous display update.

        This method blocks for ~20-25 seconds during the e-ink refresh.

        Args:
            image: PIL Image to display.
            saturation: Color saturation (0.0-1.0).

        Raises:
            DisplayError: If image dimensions don't match display dimensions.

        """
        # Normalise to landscape: the Inky library always expects the wider
        # dimension as width, and handles any physical mounting rotation
        # internally (hard-coded rot90 in InkyEL133UF1.show()).
        if image.height > image.width:
            image = image.transpose(Image.Transpose.ROTATE_90)

        if image.size != (self.width, self.height):
            raise DisplayError(
                f"Image size {image.size[0]}x{image.size[1]} does not match display size {self.width}x{self.height}."
            )

        logger.info("Updating display (this takes ~20-25 seconds)...")
        # The buffer set here persists on the driver object across show() calls,
        # so retries re-send the same image without re-converting it.
        self._display.set_image(image, saturation=saturation)

        last_failure: str | None = None
        for attempt in range(1, self._max_refresh_attempts + 1):
            last_failure = self._run_show_once()
            if last_failure is None:
                logger.info("Display update complete")
                return
            logger.warning(
                "Display refresh attempt %d/%d did not complete (%s)",
                attempt,
                self._max_refresh_attempts,
                last_failure,
            )
            if attempt < self._max_refresh_attempts:
                time.sleep(self._retry_delay_s)

        raise DisplayError(f"Display refresh failed after {self._max_refresh_attempts} attempts: {last_failure}")

    def _busy_state(self) -> bool | None:
        """Read the panel BUSY line through the Inky driver's own gpiod handle.

        Returns True if BUSY is asserted (refresh in progress), False if idle,
        or None if it can't be read — a mock panel, an Inky driver that exposes
        the line differently, or any read error. The driver owns the line, so we
        reuse its handle rather than requesting the pin again (which would
        clash); reads run concurrently with the driver's own and are guarded so
        a gpiod hiccup degrades to "unknown" instead of breaking the refresh.
        """
        gpio = getattr(self._display, "_gpio", None)
        busy_pin = getattr(self._display, "busy_pin", None)
        if gpio is None or busy_pin is None:
            return None
        try:
            return _busy_is_asserted(gpio.get_value(busy_pin))
        except Exception:
            return None

    def _run_show_once(self) -> str | None:
        """Drive one refresh; return a failure reason, or None if it completed.

        Two independent stall signals, because neither panel family exposes a
        single reliable one (see the module-level comment):

        * the driver's ``warnings.warn("... timed out ...")`` (UC8159), and
        * direct BUSY-pin watching (EL133UF1, which never warns): BUSY is
          sampled in a background thread for the duration of ``show()``. A
          healthy refresh drives it active (high) then inactive (low);
          never-active means no waveform ran, still-active afterwards means it
          stalled mid-update. When BUSY can't be read we fall back to the
          warning signal alone.

        Returns:
            None if the refresh completed, otherwise a human-readable reason the
            caller carries into the retry loop and the device-health ack.

        Raises:
            DisplayError: For hard SPI access failures, which are not retryable.

        """
        went_busy = False
        busy_observed = False
        stop = threading.Event()

        def _watch() -> None:
            nonlocal went_busy, busy_observed
            while not stop.is_set():
                state = self._busy_state()
                if state is not None:
                    busy_observed = True
                    if state:
                        went_busy = True
                stop.wait(self._busy_poll_interval_s)

        # Always start the watcher rather than gating on _gpio being present:
        # the EL133UF1 driver only creates its gpiod handle inside the first
        # show() -> setup() (~0.7 s in), so _gpio is absent when the very first
        # refresh begins. Gating here would miss that refresh; instead
        # _busy_state() returns None until the handle appears, and busy_observed
        # flips only once a real reading lands. Panels that never expose the line
        # just yield all-None samples and fall back to the warning signal.
        watcher = threading.Thread(target=_watch, name="inky-busy-watch", daemon=True)
        watcher.start()

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    self._display.show(busy_wait=True)
                except FileNotFoundError as e:
                    msg = "SPI device not found. Ensure SPI is enabled via raspi-config and reboot."
                    raise DisplayError(msg) from e
                except PermissionError as e:
                    msg = "Permission denied accessing SPI device. Add user to 'spi' group and re-login."
                    raise DisplayError(msg) from e
        finally:
            stop.set()
            watcher.join(timeout=1.0)

        for w in caught:
            # The driver's setup() re-detects the Pi model on every show() by
            # opening /proc/device-tree/model and leaking the handle, so each
            # refresh emits a benign ResourceWarning about the unclosed file.
            # It's not operator-actionable (a /proc handle the GC reclaims), so
            # keep it out of the warning stream; the checks below still run.
            if issubclass(w.category, ResourceWarning):
                logger.debug("Inky driver ResourceWarning during refresh: %s", w.message)
                continue
            logger.warning("Inky driver warning during refresh: %s", w.message)

        reason = _classify_refresh(
            timed_out=any("timed out" in str(w.message).lower() for w in caught),
            busy_observed=busy_observed,
            went_busy=went_busy,
            still_busy=self._busy_state(),
        )
        if reason is not None:
            logger.warning("Display refresh did not complete: %s", reason)
        return reason

    async def clear(self) -> None:
        """Clear the display to white."""
        white_image = Image.new("RGB", (self.width, self.height), (255, 255, 255))
        await self.show_image(white_image)

    def close(self) -> None:
        """Clean up resources."""
        if self._executor:
            self._executor.shutdown(wait=False)


class MockDisplay:
    """Mock display for testing without hardware.

    Stores the last displayed image for inspection in tests.
    """

    def __init__(self, width: int = 1600, height: int = 1200) -> None:
        """Initialize the mock display.

        Args:
            width: Simulated display width.
            height: Simulated display height.

        """
        self._width = width
        self._height = height
        self._last_image: Image.Image | None = None
        self._display_count = 0

    @property
    def width(self) -> int:
        """Display width in pixels."""
        return self._width

    @property
    def height(self) -> int:
        """Display height in pixels."""
        return self._height

    @property
    def last_image(self) -> Image.Image | None:
        """The last image that was displayed."""
        return self._last_image

    @property
    def display_count(self) -> int:
        """Number of times show_image was called."""
        return self._display_count

    async def show_image(self, image: Image.Image, saturation: float = 0.5) -> None:
        """Store the image for inspection.

        Args:
            image: PIL Image to "display".
            saturation: Color saturation (ignored in mock).

        Raises:
            DisplayError: If image dimensions don't match display dimensions.

        """
        _ = saturation  # Unused in mock, but part of interface

        # Normalise to landscape, same as the real display
        if image.height > image.width:
            image = image.transpose(Image.Transpose.ROTATE_90)

        if image.size != (self._width, self._height):
            raise DisplayError(
                f"Image size {image.size[0]}x{image.size[1]} does not match display size {self._width}x{self._height}."
            )

        self._last_image = image.copy()
        self._display_count += 1
        logger.debug("Mock display: stored image %dx%d", image.width, image.height)
        # Simulate a brief delay (real display takes ~25s)
        await asyncio.sleep(0.1)

    async def clear(self) -> None:
        """Clear the mock display."""
        self._last_image = None
        self._display_count += 1
        logger.debug("Mock display: cleared")
        await asyncio.sleep(0.1)


def create_display(
    mock: bool = False,
    mock_profile_key: str = "inky_impression_13_spectra6",
) -> InkyDisplay | MockDisplay:
    """Create the appropriate display implementation.

    Args:
        mock: If True, create a MockDisplay for testing.
        mock_profile_key: Seeded device-profile key whose panel dimensions the
            mock should report (ignored for real hardware).

    Returns:
        The display implementation for the configured target.

    Raises:
        DisplayError: If real hardware initialization fails.

    """
    if mock:
        width, height = panel_dims_for_profile_key(mock_profile_key)
        logger.info("Creating mock display %s (%dx%d)", mock_profile_key, width, height)
        return MockDisplay(width=width, height=height)

    logger.info("Creating Inky display")
    return InkyDisplay()
