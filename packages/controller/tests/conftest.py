"""Shared pytest fixtures for display controller tests."""

import pytest
from PIL import Image


@pytest.fixture
def sample_image() -> Image.Image:
    """Create a sample test image matching the default 13.3" panel size."""
    return Image.new("RGB", (1600, 1200), color="red")
