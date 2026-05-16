"""Unit tests for the grid placement and crop logic."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
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


class TestDeriveRect:
    """Validate placement derivation from midpoint or top-left."""

    def test_midpoint_at_center(self):
        grid = _grid(80, 40)
        profile = _profile(w_cm=20, h_cm=10)
        rect = grid_service.derive_rect(
            grid,
            profile,
            "landscape",
            midpoint_x_cm=40.0,
            midpoint_y_cm=20.0,
            top_left_x_cm=None,
            top_left_y_cm=None,
        )
        assert rect.top_left_x_cm == pytest.approx(30.0)
        assert rect.top_left_y_cm == pytest.approx(15.0)
        assert rect.width_cm == pytest.approx(20.0)
        assert rect.height_cm == pytest.approx(10.0)

    def test_explicit_top_left(self):
        grid = _grid(80, 40)
        profile = _profile(w_cm=20, h_cm=10)
        rect = grid_service.derive_rect(
            grid,
            profile,
            "landscape",
            midpoint_x_cm=None,
            midpoint_y_cm=None,
            top_left_x_cm=0.0,
            top_left_y_cm=0.0,
        )
        assert rect.top_left_x_cm == 0.0
        assert rect.top_left_y_cm == 0.0

    def test_portrait_swaps_dims(self):
        grid = _grid(40, 80)
        profile = _profile(w_cm=20, h_cm=10)
        rect = grid_service.derive_rect(
            grid,
            profile,
            "portrait",
            midpoint_x_cm=5.0,
            midpoint_y_cm=10.0,
            top_left_x_cm=None,
            top_left_y_cm=None,
        )
        assert rect.width_cm == pytest.approx(10.0)
        assert rect.height_cm == pytest.approx(20.0)

    def test_rect_off_canvas_raises(self):
        grid = _grid(80, 40)
        profile = _profile(w_cm=20, h_cm=10)
        with pytest.raises(grid_service.GridValidationError) as exc:
            grid_service.derive_rect(
                grid,
                profile,
                "landscape",
                midpoint_x_cm=75.0,
                midpoint_y_cm=20.0,
                top_left_x_cm=None,
                top_left_y_cm=None,
            )
        assert exc.value.status_code == 400

    def test_no_coords_raises(self):
        grid = _grid()
        profile = _profile()
        with pytest.raises(grid_service.GridValidationError):
            grid_service.derive_rect(
                grid,
                profile,
                "landscape",
                midpoint_x_cm=None,
                midpoint_y_cm=None,
                top_left_x_cm=None,
                top_left_y_cm=None,
            )


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
