"""Tests for the display abstraction.

MockDisplay mirrors the real InkyDisplay's contract (auto-rotate portrait
input, reject wrong sizes), so these tests pin that contract without hardware.
"""

import pytest
from inky_image_display_controller.display import MockDisplay, create_display
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
