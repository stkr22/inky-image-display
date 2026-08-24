"""Tests for ImageProcessor — resize, crop, and EXIF orientation handling."""

from io import BytesIO

import pytest
from inky_image_display_api.services.image_processor import ImageProcessor, _draft_to_target
from PIL import Image

# EXIF 0x0112 = Orientation tag
_ORIENTATION_TAG = 0x0112


def _make_jpeg(img: Image.Image, orientation: int | None = None) -> bytes:
    """Encode a PIL image as JPEG, optionally tagging an EXIF orientation."""
    buf = BytesIO()
    if orientation is None:
        img.save(buf, format="JPEG")
    else:
        exif = Image.Exif()
        exif[_ORIENTATION_TAG] = orientation
        img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


class TestExifOrientation:
    def test_portrait_photo_with_orientation_6_is_rotated_before_crop(self) -> None:
        """A phone-taken portrait (landscape pixels + Orientation=6) must be
        rotated upright before resize/crop, otherwise a portrait target
        receives a landscape-content slice.

        Simulates the real bug: the top-left pixel is red so we can detect
        which corner survives the rotation. Orientation=6 means "rotate 90°
        CW on display", so the original top-left lands on the top-right.
        """
        # 400 wide x 300 tall (landscape pixels). After applying Orientation=6,
        # the upright image is 300 wide x 400 tall (portrait).
        # Use large blocks (not single pixels) so JPEG compression doesn't
        # wash out the marker colors.
        raw = Image.new("RGB", (400, 300), color=(255, 255, 255))
        # Paint the left half red (in raw/landscape coordinates).
        # After Orientation=6 (rotate 90° CW), the left half becomes the top
        # half of the upright portrait image.
        for x in range(200):
            for y in range(300):
                raw.putpixel((x, y), (255, 0, 0))

        data = _make_jpeg(raw, orientation=6)

        processed_bytes = ImageProcessor.process_for_display(data, target_width=150, target_height=200, upscale=True)
        assert processed_bytes is not None

        out = Image.open(BytesIO(processed_bytes))
        # Target was portrait; output must be portrait.
        assert out.size == (150, 200), f"expected portrait output, got {out.size}"

        # After rotation, red should occupy the top half of the output.
        # Sample a pixel near the top-center; it must be red.
        top_pixel = out.getpixel((out.width // 2, 10))
        assert isinstance(top_pixel, tuple)
        r, g, b = top_pixel[0], top_pixel[1], top_pixel[2]
        assert r > 200 and g < 80 and b < 80, (
            f"EXIF orientation was not applied: top-center pixel is {top_pixel}, expected red"
        )

        # And a pixel near the bottom-center should be white (was the right
        # half of the original landscape pixels).
        bottom_pixel = out.getpixel((out.width // 2, out.height - 10))
        assert isinstance(bottom_pixel, tuple)
        r, g, b = bottom_pixel[0], bottom_pixel[1], bottom_pixel[2]
        assert r > 200 and g > 200 and b > 200, f"Bottom-center pixel should be white, got {bottom_pixel}"

    def test_image_without_exif_orientation_is_unchanged(self) -> None:
        """Images without an orientation tag must process identically to before."""
        raw = Image.new("RGB", (400, 300), color=(128, 128, 128))
        data = _make_jpeg(raw)

        processed = ImageProcessor.process_for_display(data, target_width=200, target_height=100)
        assert processed is not None
        out = Image.open(BytesIO(processed))
        assert out.size == (200, 100)

    def test_cover_fit_never_undershoots_target_by_rounding(self) -> None:
        """Regression: a 2156x1617 source cover-fitted to 1600x1200 used to
        floor the overflow axis to 1599, which the controller rejected with
        'Image size 1599x1200 does not match display size 1600x1200'."""
        raw = Image.new("RGB", (2156, 1617), color=(100, 150, 200))
        processed = ImageProcessor.process_for_display(_make_jpeg(raw), target_width=1600, target_height=1200)
        assert processed is not None
        assert Image.open(BytesIO(processed)).size == (1600, 1200)

    @pytest.mark.parametrize("orientation", [3, 6, 8])
    def test_rotation_orientations_produce_portrait_output(self, orientation: int) -> None:
        """All rotation orientations (180°, 90° CW, 90° CCW) must resolve
        before crop so a portrait target receives portrait-shaped content."""
        # Pixels are landscape; for orientation 6 and 8 the upright shape is
        # portrait. For orientation 3 (180° rotate) shape stays landscape.
        raw = Image.new("RGB", (400, 300), color=(200, 50, 50))
        data = _make_jpeg(raw, orientation=orientation)

        processed = ImageProcessor.process_for_display(data, target_width=150, target_height=200, upscale=True)
        assert processed is not None
        out = Image.open(BytesIO(processed))
        assert out.size == (150, 200)


class TestDraftReduction:
    """``draft()`` keeps peak RSS down by decoding JPEGs at a reduced scale.

    These assert the *contract* the memory fix relies on — that the decoder is
    actually asked for a smaller raster, and that it is never asked for one
    too small to cover the target. RSS itself is not asserted: it is a
    process-global high-water mark and far too noisy for a unit test.
    """

    @staticmethod
    def _decoded_size(data: bytes, target: tuple[int, int]) -> tuple[int, int]:
        """Size Pillow would actually decode for this source/target pair."""
        with Image.open(BytesIO(data)) as img:
            _draft_to_target(img, *target)
            return img.size

    def test_large_jpeg_decodes_at_reduced_scale(self) -> None:
        """A 4000x3000 source for a 1600x1200 target must not decode at full
        size — that 36MB raster times concurrent requests is the OOM."""
        raw = Image.new("RGB", (4000, 3000), color=(90, 140, 190))
        assert self._decoded_size(_make_jpeg(raw), (1600, 1200)) == (2000, 1500)

    def test_reduced_raster_still_covers_target(self) -> None:
        """draft() halves in powers of two, so the guarantee we need is only
        that it never lands *below* the target on either axis."""
        raw = Image.new("RGB", (4000, 3000), color=(90, 140, 190))
        width, height = self._decoded_size(_make_jpeg(raw), (1200, 900))
        assert width >= 1200 and height >= 900

    def test_rotating_orientation_swaps_the_drafted_axes(self) -> None:
        """Regression guard: draft() runs *before* exif_transpose, so for a
        90-degree orientation the target axes have to be swapped first.
        Drafting 4000x3000 against 1600x1200 gives 2000x1500, which transposes
        to 1500x2000 — 100px short of the 1600 the cover-crop needs."""
        raw = Image.new("RGB", (4000, 3000), color=(90, 140, 190))
        data = _make_jpeg(raw, orientation=6)
        # Portrait target, because Orientation=6 makes the upright image portrait.
        assert self._decoded_size(data, (1200, 1600)) == (2000, 1500)

    def test_rotated_source_still_produces_exact_target(self) -> None:
        """End-to-end form of the above: output must match the target exactly,
        not fall short because draft() over-reduced."""
        raw = Image.new("RGB", (4000, 3000), color=(90, 140, 190))
        processed = ImageProcessor.process_for_display(
            _make_jpeg(raw, orientation=6), target_width=1200, target_height=1600
        )
        assert processed is not None
        assert Image.open(BytesIO(processed)).size == (1200, 1600)

    def test_source_smaller_than_target_is_not_reduced(self) -> None:
        """Undersized sources must reach the upscale/None decision untouched."""
        raw = Image.new("RGB", (1500, 1300), color=(90, 140, 190))
        assert self._decoded_size(_make_jpeg(raw), (1600, 1200)) == (1500, 1300)

    def test_non_jpeg_is_unaffected(self) -> None:
        """PNG (and HEIC) have no scaled-decode support; draft() must no-op
        rather than raise, so those paths keep working unchanged."""
        raw = Image.new("RGB", (4000, 3000), color=(90, 140, 190))
        buf = BytesIO()
        raw.save(buf, format="PNG")
        assert self._decoded_size(buf.getvalue(), (1600, 1200)) == (4000, 3000)

        processed = ImageProcessor.process_for_display(buf.getvalue(), target_width=1600, target_height=1200)
        assert processed is not None
        assert Image.open(BytesIO(processed)).size == (1600, 1200)
