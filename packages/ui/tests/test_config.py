"""Settings loader tests."""

from __future__ import annotations

import os

import pytest
from inky_image_display_ui.config import Settings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _clear_ui_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear any UI_* env vars inherited from the dev shell / compose."""
    for key in list(os.environ):
        if key.startswith("UI_"):
            monkeypatch.delenv(key, raising=False)


def test_required_fields_missing_raises() -> None:
    with pytest.raises(ValidationError):
        Settings()  # ty: ignore[missing-argument]


def test_defaults_populate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_API_BASE_URL", "http://api.test:8000/")
    monkeypatch.setenv("UI_S3_ENDPOINT", "minio.test:9000")
    monkeypatch.setenv("UI_S3_READER_ACCESS_KEY", "reader")
    monkeypatch.setenv("UI_S3_READER_SECRET_KEY", "reader-secret")

    settings = Settings()  # ty: ignore[missing-argument]

    assert settings.api_base_url == "http://api.test:8000"  # trailing slash stripped
    assert settings.api_timeout_seconds == 30.0
    assert settings.s3_bucket == "inky-images"
    assert settings.s3_secure is False
    assert settings.s3_region is None
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.media_cache_max_age == 86400


def test_trailing_slash_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_API_BASE_URL", "http://api.test:8000///")
    monkeypatch.setenv("UI_S3_ENDPOINT", "minio.test:9000")
    monkeypatch.setenv("UI_S3_READER_ACCESS_KEY", "r")
    monkeypatch.setenv("UI_S3_READER_SECRET_KEY", "rs")

    settings = Settings()  # ty: ignore[missing-argument]

    assert settings.api_base_url == "http://api.test:8000"
