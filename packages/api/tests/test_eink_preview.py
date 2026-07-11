"""Tests for the Spectra 6 e-ink render preview."""

from io import BytesIO
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from inky_image_display_api.services.eink_preview import render_eink_preview
from PIL import Image as PILImage


def _gradient_jpeg(width: int = 64, height: int = 48) -> bytes:
    image = PILImage.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (x * 4 % 256, y * 5 % 256, (x + y) * 3 % 256))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class TestRenderEinkPreview:
    def test_output_is_png_with_at_most_six_ink_colours(self) -> None:
        preview = render_eink_preview(_gradient_jpeg())
        with PILImage.open(BytesIO(preview)) as rendered:
            assert rendered.format == "PNG"
            colours = rendered.convert("RGB").getcolors(maxcolors=4096)
        assert colours is not None
        assert len(colours) <= 6

    def test_saturation_changes_the_mapping(self) -> None:
        low = render_eink_preview(_gradient_jpeg(), saturation=0.0)
        high = render_eink_preview(_gradient_jpeg(), saturation=1.0)
        assert low != high


class TestEinkPreviewEndpoints:
    def test_upload_preview_returns_png(self, client: TestClient) -> None:
        response = client.post(
            "/api/images/eink-preview",
            files={"file": ("test.jpg", _gradient_jpeg(), "image/jpeg")},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_upload_preview_rejects_non_image(self, client: TestClient) -> None:
        response = client.post(
            "/api/images/eink-preview",
            files={"file": ("test.txt", b"not an image", "text/plain")},
        )
        assert response.status_code == 422

    async def test_stored_image_preview_renders_and_caches(
        self, client: TestClient, seed_image, mock_s3_service: MagicMock
    ) -> None:
        original = _gradient_jpeg()

        def fake_get(key: str) -> bytes:
            if key.startswith("thumbs/eink/"):
                raise FileNotFoundError(key)  # cache miss
            return original

        mock_s3_service.get_object_bytes = MagicMock(side_effect=fake_get)

        response = client.get(f"/api/images/{seed_image.id}/eink-preview")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        # Rendered preview was written back to the cache key.
        cached_key = mock_s3_service.upload_image.call_args[0][0]
        assert cached_key.startswith("thumbs/eink/s05/")

    def test_unknown_image_is_404(self, client: TestClient) -> None:
        assert client.get(f"/api/images/{uuid4()}/eink-preview").status_code == 404
