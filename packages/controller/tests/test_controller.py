"""Tests for the display abstraction.

MockDisplay mirrors the real InkyDisplay's contract (auto-rotate portrait
input, reject wrong sizes), so these tests pin that contract without hardware.
"""

import warnings

import pytest
from inky_image_display_controller.display import InkyDisplay, MockDisplay, create_display
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


class _FakeInkyPanel:
    """Stand-in for the Inky driver object injected into InkyDisplay.

    Reproduces the driver's quirk: a stalled refresh emits a warnings.warn()
    and returns (instead of raising), so show() looks successful. ``timeouts``
    controls how many leading show() calls stall before one succeeds;
    ``fail_forever`` stalls every call.
    """

    def __init__(  # noqa: PLR0913 — test stub mirrors the driver's failure modes
        self,
        width: int = 1600,
        height: int = 1200,
        timeouts: int = 0,
        fail_forever: bool = False,
        raise_exc: Exception | None = None,
        resource_warn: bool = False,
    ) -> None:
        self.width = width
        self.height = height
        self._timeouts = timeouts
        self._fail_forever = fail_forever
        self._raise_exc = raise_exc
        self._resource_warn = resource_warn
        self.show_calls = 0
        self.set_image_calls = 0
        self.last_saturation: float | None = None

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
        if self._fail_forever or self.show_calls <= self._timeouts:
            warnings.warn("Busy Wait: Timed out after 32.00s", stacklevel=1)


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
