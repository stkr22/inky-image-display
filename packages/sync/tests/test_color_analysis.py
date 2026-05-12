from io import BytesIO

from inky_image_display_shared.utils.color_analysis import ColorProfileAnalyzer
from PIL import Image


def _image_to_bytes(img: Image.Image) -> bytes:
    """Save a PIL image to JPEG bytes."""
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestCalculateVibrancyScore:
    def test_vibrant_color_image_scores_high(self) -> None:
        """Image with saturated colors should score high via saturation."""
        img = Image.new("RGB", (200, 200))
        # Fill with saturated colors: red, green, blue, yellow quadrants
        for x in range(200):
            for y in range(200):
                if x < 100 and y < 100:
                    img.putpixel((x, y), (255, 0, 0))
                elif x >= 100 and y < 100:
                    img.putpixel((x, y), (0, 200, 0))
                elif x < 100 and y >= 100:
                    img.putpixel((x, y), (0, 0, 255))
                else:
                    img.putpixel((x, y), (255, 255, 0))

        score = ColorProfileAnalyzer.calculate_vibrancy_score(_image_to_bytes(img))
        assert score > 0.5, f"Vibrant color image should score > 0.5, got {score}"

    def test_high_contrast_bw_image_gets_contrast_bonus(self) -> None:
        """B&W image scores via contrast bonus, but lower than saturated images."""
        img = Image.new("RGB", (200, 200))
        # Left half black, right half white
        for x in range(200):
            for y in range(200):
                if x < 100:
                    img.putpixel((x, y), (0, 0, 0))
                else:
                    img.putpixel((x, y), (255, 255, 255))

        score = ColorProfileAnalyzer.calculate_vibrancy_score(_image_to_bytes(img))
        # Contrast bonus only (~0.3 * 1.0) — no saturation contribution
        assert 0.2 < score < 0.5, f"B&W image should score 0.2-0.5 via contrast bonus, got {score}"

    def test_uniform_mid_gray_scores_low(self) -> None:
        """Uniform mid-gray image: no saturation, no contrast -> low score."""
        img = Image.new("RGB", (200, 200), color=(120, 115, 110))

        score = ColorProfileAnalyzer.calculate_vibrancy_score(_image_to_bytes(img))
        assert score < 0.15, f"Uniform gray image should score < 0.15, got {score}"

    def test_all_black_image_scores_low(self) -> None:
        """All-black image has no contrast and no meaningful saturation."""
        img = Image.new("RGB", (200, 200), color=(0, 0, 0))

        score = ColorProfileAnalyzer.calculate_vibrancy_score(_image_to_bytes(img))
        assert score < 0.1, f"All-black image should score < 0.1, got {score}"

    def test_dark_but_saturated_image_passes(self) -> None:
        """Dark but colorful image should pass via saturation."""
        img = Image.new("RGB", (200, 200))
        # Dark red and dark blue halves
        for x in range(200):
            for y in range(200):
                if x < 100:
                    img.putpixel((x, y), (120, 20, 20))
                else:
                    img.putpixel((x, y), (20, 20, 120))

        score = ColorProfileAnalyzer.calculate_vibrancy_score(_image_to_bytes(img))
        assert score > 0.3, f"Dark but saturated image should score > 0.3, got {score}"

    def test_score_in_valid_range(self) -> None:
        """Score should always be between 0.0 and 1.0."""
        for color in [(0, 0, 0), (128, 128, 128), (255, 255, 255), (255, 0, 0)]:
            img = Image.new("RGB", (50, 50), color=color)
            score = ColorProfileAnalyzer.calculate_vibrancy_score(_image_to_bytes(img))
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for color {color}"
