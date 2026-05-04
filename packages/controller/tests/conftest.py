"""Shared pytest fixtures for display controller tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from inky_image_display_controller.config import (
    APIConfig,
    DeviceConfig,
    DisplayConfig,
    MQTTConfig,
    S3Config,
    Settings,
)
from inky_image_display_controller.display import MockDisplay
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DisplayCommand,
    DisplayInfo,
    RegistrationResponse,
)
from PIL import Image


@pytest.fixture
def sample_image() -> Image.Image:
    """Create a sample test image."""
    return Image.new("RGB", (1600, 1200), color="red")


@pytest.fixture
def mock_display() -> MockDisplay:
    """Create a mock display for testing."""
    return MockDisplay()


@pytest.fixture
def mock_mqtt_client() -> AsyncMock:
    """Create a mock MQTT client."""
    client = AsyncMock()
    client.publish_ack = AsyncMock()
    client.run = AsyncMock()
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def mock_s3_client() -> MagicMock:
    """Create a mock S3 client."""
    client = MagicMock()
    client.is_configured = True
    client.configure = MagicMock()
    client.fetch_image = AsyncMock(return_value=Image.new("RGB", (1600, 1200), "blue"))
    client.close = MagicMock()
    return client


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        device=DeviceConfig(id="test-device", room="Test Room"),
        api=APIConfig(url="http://localhost:8000"),
        mqtt=MQTTConfig(host="broker.test"),
        s3=S3Config(endpoint="localhost:9000", bucket="test-bucket"),
        display=DisplayConfig(mock=True),
    )


@pytest.fixture
def sample_device_registration() -> DeviceRegistration:
    """Create a sample device registration."""
    return DeviceRegistration(
        device_id="test-device",
        display=DisplayInfo(
            width=1600,
            height=1200,
            orientation="landscape",
            model="inky_impression_13_spectra6",
        ),
        room="Test Room",
    )


@pytest.fixture
def sample_registration_response() -> RegistrationResponse:
    """Create a sample registration response."""
    return RegistrationResponse(
        status="registered",
        s3_endpoint="s3.test.local:9000",
        s3_bucket="test-images",
        s3_access_key="test-access-key",
        s3_secret_key="test-secret-key",
        s3_secure=False,
    )


@pytest.fixture
def sample_display_command() -> DisplayCommand:
    """Create a sample display command."""
    return DisplayCommand(
        action="display",
        image_path="images/test.png",
        image_id="test-image-123",
        title="Test Image",
    )


@pytest.fixture
def sample_clear_command() -> DisplayCommand:
    """Create a sample clear command."""
    return DisplayCommand(action="clear")


@pytest.fixture
def sample_acknowledge() -> DeviceAcknowledge:
    """Create a sample acknowledgment."""
    return DeviceAcknowledge(
        device_id="test-device",
        image_id="test-image-123",
        successful_display_change=True,
        error=None,
    )
