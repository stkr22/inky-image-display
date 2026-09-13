"""Tests for derived ``Settings`` properties."""

from __future__ import annotations

from inky_image_display_api.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build Settings with the required fields filled in."""
    return Settings(
        database_path="/tmp/test.db",
        s3_endpoint="garage.storage.svc:3900",
        s3_writer_access_key="wk",
        s3_writer_secret_key="ws",
        s3_reader_access_key="rk",
        s3_reader_secret_key="rs",
        mqtt_host="broker.svc",
        device_mqtt_host="mqtt.example.com",
        **overrides,  # ty: ignore[invalid-argument-type]
    )


class TestControllerS3:
    """Controllers may reach the bucket over a different network path."""

    def test_falls_back_to_api_endpoint(self):
        # Single-endpoint deployments configure only the API's own values.
        settings = _settings(s3_secure=True)
        assert settings.controller_s3_endpoint == "garage.storage.svc:3900"
        assert settings.controller_s3_secure is True

    def test_device_override_wins(self):
        settings = _settings(s3_secure=False, device_s3_endpoint="s3.example.com", device_s3_secure=True)
        assert settings.controller_s3_endpoint == "s3.example.com"
        assert settings.controller_s3_secure is True
