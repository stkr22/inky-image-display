"""Display abstraction layer for Inky e-paper displays."""

import asyncio
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from inky_image_display_controller.exceptions import DisplayError

logger = logging.getLogger(__name__)


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


class DisplayInterface(ABC):
    """Abstract interface for display implementations."""

    @property
    @abstractmethod
    def width(self) -> int:
        """Display width in pixels."""

    @property
    @abstractmethod
    def height(self) -> int:
        """Display height in pixels."""

    @abstractmethod
    async def show_image(self, image: Image.Image, saturation: float = 0.5) -> None:
        """Display an image on the screen.

        Args:
            image: PIL Image to display.
            saturation: Color saturation for Spectra 6 displays (0.0-1.0).

        """

    @abstractmethod
    async def clear(self) -> None:
        """Clear the display to white."""


class InkyDisplay(DisplayInterface):
    """Wrapper for Pimoroni Inky e-paper displays.

    The display refresh is a blocking operation (~20-25 seconds),
    so it runs in a dedicated thread pool to avoid blocking the async loop.

    Dimensions are auto-detected from the hardware during initialization.
    The Inky library itself handles any internal rotation required by the
    physical mounting — the public API always expects landscape images
    (wider than tall).
    """

    def __init__(
        self,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        """Initialize the Inky display wrapper.

        Connects to hardware immediately to detect display dimensions.

        Args:
            executor: Optional thread pool executor for display operations.

        Raises:
            DisplayError: If the display cannot be initialized.

        """
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="inky")
        self._lock = asyncio.Lock()

        # Eager init - get dimensions from hardware
        try:
            from inky.auto import auto  # noqa: PLC0415  # ty: ignore[unresolved-import]

            self._display = auto()
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

        display_image = image

        logger.info("Updating display (this takes ~20-25 seconds)...")
        self._display.set_image(display_image, saturation=saturation)
        try:
            self._display.show(busy_wait=True)
        except FileNotFoundError as e:
            raise DisplayError("SPI device not found. Ensure SPI is enabled via raspi-config and reboot.") from e
        except PermissionError as e:
            raise DisplayError("Permission denied accessing SPI device. Add user to 'spi' group and re-login.") from e
        logger.info("Display update complete")

    async def clear(self) -> None:
        """Clear the display to white."""
        white_image = Image.new("RGB", (self.width, self.height), (255, 255, 255))
        await self.show_image(white_image)

    def close(self) -> None:
        """Clean up resources."""
        if self._executor:
            self._executor.shutdown(wait=False)


class MockDisplay(DisplayInterface):
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
) -> DisplayInterface:
    """Create the appropriate display implementation.

    Args:
        mock: If True, create a MockDisplay for testing.
        mock_profile_key: Seeded device-profile key whose panel dimensions the
            mock should report (ignored for real hardware).

    Returns:
        DisplayInterface implementation.

    Raises:
        DisplayError: If real hardware initialization fails.

    """
    if mock:
        width, height = panel_dims_for_profile_key(mock_profile_key)
        logger.info("Creating mock display %s (%dx%d)", mock_profile_key, width, height)
        return MockDisplay(width=width, height=height)

    logger.info("Creating Inky display")
    return InkyDisplay()
