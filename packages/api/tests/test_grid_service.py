"""Unit tests for the grid placement and crop logic."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from inky_image_display_api.services import grid_service
from inky_image_display_shared.models import DeviceProfile, Grid, GridDevice
from PIL import Image as PILImage


def _profile(width: int = 1600, height: int = 1200, w_cm: float = 27.1, h_cm: float = 20.3) -> DeviceProfile:
    return DeviceProfile(
        id=uuid4(),
        key=f"profile-{uuid4()}",
        name="test",
        width=width,
        height=height,
        physical_width_cm=w_cm,
        physical_height_cm=h_cm,
        model="test",
    )


def _grid(width_cm: float = 80.0, height_cm: float = 40.0) -> Grid:
    return Grid(id=uuid4(), name=f"grid-{uuid4()}", width_cm=width_cm, height_cm=height_cm)


class TestOrientedDims:
    """Physical/pixel dims swap for portrait mounts."""

    def test_portrait_swaps_physical_dims(self):
        profile = _profile(w_cm=20, h_cm=10)
        assert grid_service.oriented_physical_dims(profile, "portrait") == (10, 20)
        assert grid_service.oriented_physical_dims(profile, "landscape") == (20, 10)

    def test_portrait_swaps_pixel_dims(self):
        profile = _profile(width=1600, height=1200)
        assert grid_service.oriented_pixel_dims(profile, "portrait") == (1200, 1600)


def _make_jpeg(width: int, height: int) -> bytes:
    img = PILImage.new("RGB", (width, height), color=(128, 128, 128))
    out = BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


class TestComputeCropForDevice:
    """Verify per-device crop dimensions and slice geometry."""

    def test_output_matches_target_pixel_size(self):
        grid = _grid(80, 40)
        placement = GridDevice(
            grid_id=grid.id,
            device_id=uuid4(),
            top_left_x_cm=0.0,
            top_left_y_cm=0.0,
            width_cm=20.0,
            height_cm=10.0,
        )
        src = _make_jpeg(1600, 800)  # exact canvas aspect 2:1
        out = grid_service.compute_crop_for_device(src, grid, placement, (640, 320))
        with PILImage.open(BytesIO(out)) as decoded:
            assert decoded.size == (640, 320)

    def test_wider_source_centre_crops_horizontally(self):
        """A 3:1 image on a 2:1 canvas should drop the side regions."""
        grid = _grid(80, 40)
        placement = GridDevice(
            grid_id=grid.id,
            device_id=uuid4(),
            top_left_x_cm=0.0,
            top_left_y_cm=0.0,
            width_cm=80.0,
            height_cm=40.0,
        )
        src = _make_jpeg(2400, 800)  # 3:1
        out = grid_service.compute_crop_for_device(src, grid, placement, (800, 400))
        with PILImage.open(BytesIO(out)) as decoded:
            assert decoded.size == (800, 400)
