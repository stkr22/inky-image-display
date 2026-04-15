"""Display abstraction layer for Inky e-paper displays."""

import asyncio
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from inky_image_display_controller.exceptions import DisplayError

logger = logging.getLogger(__name__)


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
            from inky.auto import auto  # ty: ignore[unresolved-import]  # noqa: PLC0415

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
    mock_width: int = 1600,
    mock_height: int = 1200,
) -> DisplayInterface:
    """Create the appropriate display implementation.

    Args:
        mock: If True, create a MockDisplay for testing.
        mock_width: Width for mock display (ignored for real hardware).
        mock_height: Height for mock display (ignored for real hardware).

    Returns:
        DisplayInterface implementation.

    Raises:
        DisplayError: If real hardware initialization fails.

    """
    if mock:
        logger.info("Creating mock display (%dx%d)", mock_width, mock_height)
        return MockDisplay(width=mock_width, height=mock_height)

    logger.info("Creating Inky display")
    return InkyDisplay()
