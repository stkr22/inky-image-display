"""Tests for the display abstraction.

MockDisplay mirrors the real InkyDisplay's contract (auto-rotate portrait
input, reject wrong sizes), so these tests pin that contract without hardware.
"""

import time
import warnings

import pytest
from inky_image_display_controller.display import (
    InkyDisplay,
    MockDisplay,
    _busy_is_asserted,
    _classify_refresh,
    create_display,
)
from inky_image_display_controller.exceptions import DisplayError
from PIL import Image


class TestDisplayContract:
    @pytest.mark.asyncio
    async def test_show_then_clear(self, sample_image: Image.Image) -> None:
        display = MockDisplay()
        await display.show_image(sample_image)
        assert display.last_image is not None
        assert display.last_image.size == sample_image.size

        await display.clear()
        assert display.last_image is None

    def test_create_display_resolves_mock_profile_dimensions(self) -> None:
        """create_display maps the profile key to the panel's pixel dimensions."""
        display = create_display(mock=True, mock_profile_key="inky_impression_13_spectra6")
        assert display.width == 1600
        assert display.height == 1200

    @pytest.mark.asyncio
    async def test_portrait_image_auto_rotated_to_landscape(self) -> None:
        """The display layer normalises portrait input to its landscape panel."""
        display = create_display(mock=True, mock_profile_key="inky_impression_13_spectra6")
        assert isinstance(display, MockDisplay)
        portrait_image = Image.new("RGB", (1200, 1600), "blue")
        await display.show_image(portrait_image)
        assert display.last_image is not None
        assert display.last_image.size == (1600, 1200)

    @pytest.mark.asyncio
    async def test_wrong_image_size_raises_error(self) -> None:
        display = MockDisplay()
        wrong_size_image = Image.new("RGB", (800, 600), "green")

        with pytest.raises(DisplayError) as exc_info:
            await display.show_image(wrong_size_image)

        assert "800x600" in str(exc_info.value)
        assert "1600x1200" in str(exc_info.value)
        assert display.last_image is None  # No display update happened


class _FakeBusyValue:
    """Minimal stand-in for gpiod's ``Value`` enum — only ``.name`` is read."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeGpio:
    """Stand-in for the EL133UF1 driver's gpiod request handle.

    Reports the BUSY line off the panel's ``busy_low`` flag: active-low BUSY_N
    reads ``INACTIVE`` (low) while the panel claims to be mid-refresh.
    """

    def __init__(self, panel: "_FakeInkyPanel") -> None:
        self._panel = panel

    def get_value(self, pin: int) -> _FakeBusyValue:
        return _FakeBusyValue("INACTIVE" if self._panel.busy_low else "ACTIVE")


class _FakeInkyPanel:
    """Stand-in for the Inky driver object injected into InkyDisplay.

    Reproduces the driver's quirk: a stalled refresh emits a warnings.warn()
    and returns (instead of raising), so show() looks successful. ``timeouts``
    controls how many leading show() calls stall before one succeeds;
    ``fail_forever`` stalls every call. ``busy_profile`` simulates the silent
    EL133UF1 case via a gpiod-like BUSY line: ``"asserts"`` drives BUSY low then
    high (healthy), ``"never"`` keeps it high (no waveform), ``"stuck"`` leaves
    it low (stalled mid-update). A busy profile is the only thing that exposes a
    ``_gpio``/``busy_pin``, so the default fake stays on the warning-only path.
    """

    def __init__(  # noqa: PLR0913 — test stub mirrors the driver's failure modes
        self,
        width: int = 1600,
        height: int = 1200,
        timeouts: int = 0,
        fail_forever: bool = False,
        raise_exc: Exception | None = None,
        resource_warn: bool = False,
        busy_profile: str | None = None,
        gpio_lazy: bool = False,
    ) -> None:
        self.width = width
        self.height = height
        self._timeouts = timeouts
        self._fail_forever = fail_forever
        self._raise_exc = raise_exc
        self._resource_warn = resource_warn
        self._busy_profile = busy_profile
        self._gpio_lazy = gpio_lazy
        self.show_calls = 0
        self.set_image_calls = 0
        self.last_saturation: float | None = None
        self.busy_low = False
        if busy_profile is not None and not gpio_lazy:
            self._attach_gpio()

    def _attach_gpio(self) -> None:
        # Mirrors the EL133UF1 driver creating its gpiod handle inside setup().
        self.busy_pin = 17
        self._gpio = _FakeGpio(self)

    def set_image(self, image: Image.Image, saturation: float = 0.5) -> None:
        self.set_image_calls += 1
        self.last_saturation = saturation

    def show(self, busy_wait: bool = True) -> None:
        self.show_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._resource_warn:
            # Mirrors the driver's setup() leaking /proc/device-tree/model on
            # every refresh — a benign ResourceWarning that must not be treated
            # as a stall nor surfaced at warning level.
            warnings.warn(
                "unclosed file <_io.TextIOWrapper name='/proc/device-tree/model' mode='r'>",
                ResourceWarning,
                stacklevel=1,
            )
        if self._busy_profile is not None:
            if self._gpio_lazy and not hasattr(self, "_gpio"):
                self._attach_gpio()  # the real driver attaches its handle ~0.7s into show()
            self._simulate_busy()
        if self._fail_forever or self.show_calls <= self._timeouts:
            warnings.warn("Busy Wait: Timed out after 32.00s", stacklevel=1)

    def _simulate_busy(self) -> None:
        # Hold the line in the profile's "during refresh" state long enough for
        # the watcher thread to sample it (~50 ms >> the test poll interval).
        if self._busy_profile in ("asserts", "stuck"):
            self.busy_low = True
        time.sleep(0.05)
        if self._busy_profile == "asserts":
            self.busy_low = False


def _landscape_image() -> Image.Image:
    return Image.new("RGB", (1600, 1200), "white")


class TestInkyRefreshRecovery:
    """InkyDisplay must detect a swallowed busy-timeout and reset-and-retry."""

    @pytest.mark.asyncio
    async def test_successful_refresh_does_not_retry(self) -> None:
        panel = _FakeInkyPanel()
        display = InkyDisplay(_display=panel, retry_delay_s=0.0)
        await display.show_image(_landscape_image(), saturation=0.3)
        assert panel.show_calls == 1
        assert panel.set_image_calls == 1
        assert panel.last_saturation == 0.3

    @pytest.mark.asyncio
    async def test_retries_after_busy_timeout_then_succeeds(self) -> None:
        # First show() stalls (warns), second completes — image should display.
        panel = _FakeInkyPanel(timeouts=1)
        display = InkyDisplay(_display=panel, retry_delay_s=0.0)
        await display.show_image(_landscape_image())
        assert panel.show_calls == 2

    @pytest.mark.asyncio
    async def test_raises_after_exhausting_attempts(self) -> None:
        panel = _FakeInkyPanel(fail_forever=True)
        display = InkyDisplay(_display=panel, retry_delay_s=0.0, max_refresh_attempts=3)
        with pytest.raises(DisplayError) as exc_info:
            await display.show_image(_landscape_image())
        assert panel.show_calls == 3
        assert "3 attempts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_driver_resource_warning_is_not_a_stall(self, caplog: pytest.LogCaptureFixture) -> None:
        # The driver leaks /proc/device-tree/model on every refresh. That benign
        # ResourceWarning must not be mistaken for a stall (no retry) nor logged
        # at warning level as a refresh problem.
        panel = _FakeInkyPanel(resource_warn=True)
        display = InkyDisplay(_display=panel, retry_delay_s=0.0)
        with caplog.at_level("WARNING"):
            await display.show_image(_landscape_image())
        assert panel.show_calls == 1  # treated as success, not a stall
        assert "Inky driver warning during refresh" not in caplog.text

    @pytest.mark.asyncio
    async def test_spi_errors_are_not_retried(self) -> None:
        panel = _FakeInkyPanel(raise_exc=FileNotFoundError("/dev/spidev0.0"))
        display = InkyDisplay(_display=panel, retry_delay_s=0.0)
        with pytest.raises(DisplayError) as exc_info:
            await display.show_image(_landscape_image())
        assert panel.show_calls == 1  # hard SPI failure is fatal, no retry
        assert "SPI device not found" in str(exc_info.value)


class TestBusyInterpretation:
    """_busy_is_asserted maps gpiod values to a busy/idle/unknown tri-state."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (_FakeBusyValue("INACTIVE"), True),  # low = busy (active-low BUSY_N)
            (_FakeBusyValue("ACTIVE"), False),  # high = idle
            (_FakeBusyValue("garbage"), None),
            (0, True),
            (1, False),
            (False, True),
            (True, False),
            (object(), None),
        ],
    )
    def test_interpretation(self, value: object, expected: bool | None) -> None:
        assert _busy_is_asserted(value) is expected


class TestClassifyRefresh:
    """The pure failure-classification logic, decoupled from threads/hardware."""

    def test_timeout_warning_is_failure(self) -> None:
        reason = _classify_refresh(timed_out=True, busy_observed=False, went_busy=False, still_busy=None)
        assert reason is not None and "timeout" in reason

    def test_busy_never_asserted_is_failure(self) -> None:
        reason = _classify_refresh(timed_out=False, busy_observed=True, went_busy=False, still_busy=False)
        assert reason is not None and "never asserted" in reason

    def test_still_busy_after_show_is_failure(self) -> None:
        reason = _classify_refresh(timed_out=False, busy_observed=True, went_busy=True, still_busy=True)
        assert reason is not None and "stalled mid-update" in reason

    def test_healthy_refresh_returns_none(self) -> None:
        assert _classify_refresh(timed_out=False, busy_observed=True, went_busy=True, still_busy=False) is None

    def test_unobserved_busy_is_not_invented_as_failure(self) -> None:
        # BUSY could not be read at all (mock / unsupported driver) — fall back
        # to the warning signal alone rather than inventing a stall.
        assert _classify_refresh(timed_out=False, busy_observed=False, went_busy=False, still_busy=None) is None


class TestBusyPinStallDetection:
    """Direct BUSY-pin watching catches the silent EL133UF1 stall the driver
    never warns about (and which the timed-out-string check cannot see)."""

    @pytest.mark.asyncio
    async def test_busy_asserted_then_cleared_is_success(self) -> None:
        panel = _FakeInkyPanel(busy_profile="asserts")
        display = InkyDisplay(_display=panel, retry_delay_s=0.0, busy_poll_interval_s=0.005)
        await display.show_image(_landscape_image())
        assert panel.show_calls == 1

    @pytest.mark.asyncio
    async def test_busy_never_asserted_is_detected_as_stall(self) -> None:
        # show() returns with no warning, but BUSY never went low — the
        # controller must treat it as failed and exhaust its retries.
        panel = _FakeInkyPanel(busy_profile="never")
        display = InkyDisplay(_display=panel, retry_delay_s=0.0, busy_poll_interval_s=0.005, max_refresh_attempts=2)
        with pytest.raises(DisplayError) as exc_info:
            await display.show_image(_landscape_image())
        assert panel.show_calls == 2
        assert "never asserted BUSY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_busy_stuck_low_is_detected_as_stall(self) -> None:
        panel = _FakeInkyPanel(busy_profile="stuck")
        display = InkyDisplay(_display=panel, retry_delay_s=0.0, busy_poll_interval_s=0.005, max_refresh_attempts=2)
        with pytest.raises(DisplayError) as exc_info:
            await display.show_image(_landscape_image())
        assert panel.show_calls == 2
        assert "stalled mid-update" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_lazy_gpio_handle_still_detects_stall(self) -> None:
        # The EL133UF1 driver only creates its gpiod handle inside the first
        # show() -> setup(), so _gpio is absent when the refresh begins (verified
        # live on .15: present BEFORE show = False, appears ~0.7s in). The
        # always-on watcher must still catch a never-asserted BUSY once it lands.
        panel = _FakeInkyPanel(busy_profile="never", gpio_lazy=True)
        assert not hasattr(panel, "_gpio")  # like a freshly auto()'d driver
        display = InkyDisplay(_display=panel, retry_delay_s=0.0, busy_poll_interval_s=0.005, max_refresh_attempts=1)
        with pytest.raises(DisplayError) as exc_info:
            await display.show_image(_landscape_image())
        assert "never asserted BUSY" in str(exc_info.value)
        assert hasattr(panel, "_gpio")  # handle was attached during show()
