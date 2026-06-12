"""Tests for the /media proxy (originals + on-the-fly thumbnails) and SPA serving."""

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.main import serve_frontend
from inky_image_display_api.routes import media
from minio.error import S3Error
from PIL import Image as PILImage


def _no_such_key() -> S3Error:
    return S3Error(
        code="NoSuchKey",
        message="missing",
        resource="/x",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )


def _jpeg_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), "red").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def s3() -> MagicMock:
    service = MagicMock()
    service.iter_object.side_effect = lambda _key: iter([b"image-bytes"])
    return service


@pytest.fixture
def media_app(s3: MagicMock) -> FastAPI:
    app = FastAPI()
    settings = MagicMock()
    settings.media_cache_max_age = 3600
    settings.web_dist_path = None
    app.state.settings = settings
    app.state.s3_service = s3
    app.include_router(media.router)
    app.get("/{full_path:path}", include_in_schema=False)(serve_frontend)
    return app


@pytest.fixture
def client(media_app: FastAPI) -> TestClient:
    return TestClient(media_app)


class TestOriginals:
    def test_missing_object_is_404(self, client: TestClient, s3: MagicMock) -> None:
        s3.stat_object.side_effect = _no_such_key()
        assert client.get("/media/manual/x.jpg").status_code == 404

    def test_streams_with_cache_headers(self, client: TestClient, s3: MagicMock) -> None:
        s3.stat_object.return_value = MagicMock(etag="abc", content_type="image/jpeg")
        response = client.get("/media/manual/x.jpg")
        assert response.status_code == 200
        assert response.content == b"image-bytes"
        assert response.headers["etag"] == "abc"
        assert response.headers["cache-control"] == "public, max-age=3600"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"

    def test_if_none_match_returns_304(self, client: TestClient, s3: MagicMock) -> None:
        s3.stat_object.return_value = MagicMock(etag="abc", content_type="image/jpeg")
        response = client.get("/media/manual/x.jpg", headers={"If-None-Match": "abc"})
        assert response.status_code == 304

    def test_thumbs_prefix_not_directly_addressable(self, client: TestClient) -> None:
        assert client.get("/media/thumbs/w480/manual/x.jpg").status_code == 404


class TestThumbnails:
    def test_width_snaps_to_allowed_set(self) -> None:
        assert media.snap_width(300) == 240
        assert media.snap_width(400) == 480
        assert media.snap_width(5000) == 960
        assert media.snap_width(1) == 240

    def test_cache_hit_serves_thumb(self, client: TestClient, s3: MagicMock) -> None:
        s3.stat_object.return_value = MagicMock(etag="thumb-etag", content_type="image/jpeg")
        response = client.get("/media/manual/x.jpg", params={"w": 480})
        assert response.status_code == 200
        s3.stat_object.assert_called_once_with("thumbs/w480/manual/x.jpg")
        s3.upload_image.assert_not_called()

    def test_cache_miss_generates_and_caches(self, client: TestClient, s3: MagicMock) -> None:
        original = _jpeg_bytes(1200, 800)
        # First stat (thumb) misses, second stat (original) hits.
        s3.stat_object.side_effect = [_no_such_key(), MagicMock(etag="orig", content_type="image/jpeg")]
        s3.get_object_bytes.return_value = original

        response = client.get("/media/manual/x.jpg", params={"w": 300})

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        key, thumb_bytes, content_type = s3.upload_image.call_args.args
        assert key == "thumbs/w240/manual/x.jpg"
        assert content_type == "image/jpeg"
        with PILImage.open(io.BytesIO(thumb_bytes)) as thumb:
            assert thumb.width == 240
            assert thumb.height == 160

    def test_small_original_served_without_caching(self, client: TestClient, s3: MagicMock) -> None:
        s3.stat_object.side_effect = [_no_such_key(), MagicMock(etag="orig", content_type="image/jpeg")]
        s3.get_object_bytes.return_value = _jpeg_bytes(100, 80)

        response = client.get("/media/manual/x.jpg", params={"w": 480})

        assert response.status_code == 200
        assert response.content == b"image-bytes"  # streamed original
        s3.upload_image.assert_not_called()

    def test_missing_original_with_width_is_404(self, client: TestClient, s3: MagicMock) -> None:
        s3.stat_object.side_effect = [_no_such_key(), _no_such_key()]
        assert client.get("/media/manual/x.jpg", params={"w": 480}).status_code == 404


class TestFrontendServing:
    @pytest.fixture
    def dist(self, tmp_path: Path) -> Path:
        (tmp_path / "index.html").write_text("<html>inky</html>")
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('inky')")
        return tmp_path

    def test_disabled_without_dist_path(self, client: TestClient) -> None:
        assert client.get("/some-page").status_code == 404

    def test_serves_index_and_assets_and_spa_fallback(self, media_app: FastAPI, dist: Path) -> None:
        media_app.state.settings.web_dist_path = str(dist)
        client = TestClient(media_app)
        assert client.get("/").text == "<html>inky</html>"
        assert client.get("/assets/app.js").text == "console.log('inky')"
        # Client-side route falls back to index.html.
        assert client.get("/images/123").text == "<html>inky</html>"

    def test_path_traversal_falls_back_to_index(self, media_app: FastAPI, dist: Path) -> None:
        media_app.state.settings.web_dist_path = str(dist)
        client = TestClient(media_app)
        response = client.get("/../pyproject.toml")
        assert response.status_code == 200
        assert response.text == "<html>inky</html>"
