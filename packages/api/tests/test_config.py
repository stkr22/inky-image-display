"""Tests for derived ``Settings`` properties."""

from __future__ import annotations

from .conftest import make_settings


class TestControllerS3:
    """Controllers may reach the bucket over a different network path."""

    def test_falls_back_to_api_endpoint(self):
        # Single-endpoint deployments configure only the API's own values.
        settings = make_settings(s3_secure=True)
        assert settings.controller_s3_endpoint == "s3.test.local:9000"
        assert settings.controller_s3_secure is True

    def test_device_override_wins(self):
        settings = make_settings(s3_secure=False, device_s3_endpoint="s3.example.com", device_s3_secure=True)
        assert settings.controller_s3_endpoint == "s3.example.com"
        assert settings.controller_s3_secure is True
