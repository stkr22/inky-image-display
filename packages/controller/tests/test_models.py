"""Tests for Pydantic MQTT message models."""

import pytest
from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DisplayCommand,
    DisplayInfo,
    RegistrationResponse,
)
from pydantic import ValidationError


class TestDisplayInfo:
    """Tests for DisplayInfo model."""

    def test_default_values(self) -> None:
        """Test DisplayInfo with default values."""
        info = DisplayInfo()
        assert info.width == 1600
        assert info.height == 1200
        assert info.orientation == "landscape"
        assert info.model == "inky_impression_13_spectra6"

    def test_custom_values(self) -> None:
        """Test DisplayInfo with custom values."""
        info = DisplayInfo(
            width=800,
            height=480,
            orientation="portrait",
            model="custom_display",
        )
        assert info.width == 800
        assert info.height == 480
        assert info.orientation == "portrait"
        assert info.model == "custom_display"

    def test_invalid_orientation(self) -> None:
        """Test that invalid orientation raises validation error."""
        with pytest.raises(ValidationError):
            DisplayInfo(orientation="diagonal")  # ty: ignore[invalid-argument-type]


class TestDeviceRegistration:
    """Tests for DeviceRegistration model."""

    def test_minimal_registration(self) -> None:
        """Test registration with only required fields."""
        reg = DeviceRegistration(device_id="test-device")
        assert reg.device_id == "test-device"
        assert reg.display is not None
        assert reg.room is None

    def test_full_registration(self) -> None:
        """Test registration with all fields."""
        reg = DeviceRegistration(
            device_id="living-room-display",
            display=DisplayInfo(width=1600, height=1200),
            room="Living Room",
        )
        assert reg.device_id == "living-room-display"
        assert reg.display.width == 1600
        assert reg.room == "Living Room"

    def test_json_serialization(self) -> None:
        """Test JSON serialization/deserialization."""
        reg = DeviceRegistration(device_id="test-device", room="Kitchen")
        json_str = reg.model_dump_json()
        parsed = DeviceRegistration.model_validate_json(json_str)
        assert parsed.device_id == reg.device_id
        assert parsed.room == reg.room


class TestRegistrationResponse:
    """Tests for RegistrationResponse model."""

    def test_valid_response(self) -> None:
        """Test valid registration response."""
        response = RegistrationResponse(
            status="registered",
            s3_endpoint="s3.local:9000",
            s3_bucket="images",
            s3_access_key="access123",
            s3_secret_key="secret456",
            s3_secure=True,
        )
        assert response.status == "registered"
        assert response.s3_endpoint == "s3.local:9000"
        assert response.s3_secure is True

    def test_region_defaults_to_none(self) -> None:
        """Test that s3_region is None when not provided."""
        response = RegistrationResponse(
            status="registered",
            s3_endpoint="s3.local:9000",
            s3_bucket="images",
            s3_access_key="access123",
            s3_secret_key="secret456",
        )
        assert response.s3_region is None

    def test_region_parsed_when_present(self) -> None:
        """Test that s3_region is parsed correctly."""
        response = RegistrationResponse(
            status="registered",
            s3_endpoint="s3.local:9000",
            s3_bucket="images",
            s3_access_key="access123",
            s3_secret_key="secret456",
            s3_region="garage",
        )
        assert response.s3_region == "garage"

    def test_updated_status(self) -> None:
        """Test response with 'updated' status."""
        response = RegistrationResponse(
            status="updated",
            s3_endpoint="s3.local:9000",
            s3_bucket="images",
            s3_access_key="access123",
            s3_secret_key="secret456",
        )
        assert response.status == "updated"

    def test_invalid_status(self) -> None:
        """Test that invalid status raises validation error."""
        with pytest.raises(ValidationError):
            RegistrationResponse(
                status="invalid",  # ty: ignore[invalid-argument-type]
                s3_endpoint="s3.local:9000",
                s3_bucket="images",
                s3_access_key="access123",
                s3_secret_key="secret456",
            )


class TestDisplayCommand:
    """Tests for DisplayCommand model."""

    def test_display_action(self) -> None:
        """Test display command with image."""
        cmd = DisplayCommand(
            action="display",
            image_path="photos/sunset.jpg",
            image_id="img-123",
            title="Beautiful Sunset",
        )
        assert cmd.action == "display"
        assert cmd.image_path == "photos/sunset.jpg"
        assert cmd.image_id == "img-123"
        assert cmd.title == "Beautiful Sunset"

    def test_clear_action(self) -> None:
        """Test clear command."""
        cmd = DisplayCommand(action="clear")
        assert cmd.action == "clear"
        assert cmd.image_path is None
        assert cmd.image_id is None

    def test_status_action(self) -> None:
        """Test status command."""
        cmd = DisplayCommand(action="status")
        assert cmd.action == "status"

    def test_invalid_action(self) -> None:
        """Test that invalid action raises validation error."""
        with pytest.raises(ValidationError):
            DisplayCommand(action="invalid")  # ty: ignore[invalid-argument-type]

    def test_json_parsing(self) -> None:
        """Test JSON parsing from MQTT payload."""
        json_payload = '{"action": "display", "image_path": "test.jpg", "image_id": "123"}'
        cmd = DisplayCommand.model_validate_json(json_payload)
        assert cmd.action == "display"
        assert cmd.image_path == "test.jpg"


class TestDeviceAcknowledge:
    """Tests for DeviceAcknowledge model."""

    def test_success_acknowledge(self) -> None:
        """Test successful acknowledgment."""
        ack = DeviceAcknowledge(
            device_id="test-device",
            image_id="img-123",
            successful_display_change=True,
        )
        assert ack.device_id == "test-device"
        assert ack.successful_display_change is True
        assert ack.error is None

    def test_error_acknowledge(self) -> None:
        """Test acknowledgment with error."""
        ack = DeviceAcknowledge(
            device_id="test-device",
            image_id="img-123",
            successful_display_change=False,
            error="Failed to fetch image from MinIO",
        )
        assert ack.successful_display_change is False
        assert ack.error == "Failed to fetch image from MinIO"

    def test_json_serialization(self) -> None:
        """Test JSON serialization for MQTT publishing."""
        ack = DeviceAcknowledge(
            device_id="test-device",
            successful_display_change=True,
        )
        json_str = ack.model_dump_json()
        assert "device_id" in json_str
        assert "successful_display_change" in json_str
