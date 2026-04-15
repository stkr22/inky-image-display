"""Command and response schemas for device communication.

These models define the contract between skill/API and device controllers.
Used for both MQTT and WebSocket communication.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DisplayInfo(BaseModel):
    """Display hardware characteristics sent during device registration."""

    width: int = Field(default=1600, description="Display width in pixels")
    height: int = Field(default=1200, description="Display height in pixels")
    orientation: Literal["landscape", "portrait"] = Field(default="landscape", description="Display orientation")
    model: str = Field(default="inky_impression_13_spectra6", description="Display model identifier")


class DeviceRegistration(BaseModel):
    """Device registration payload.

    Sent by the device on startup to announce itself.
    """

    device_id: str = Field(description="Unique device identifier")
    display: DisplayInfo = Field(default_factory=DisplayInfo, description="Display hardware characteristics")
    room: str | None = Field(default=None, description="Room where device is located")


class RegistrationResponse(BaseModel):
    """Response sent after successful device registration."""

    status: Literal["registered", "updated"] = Field(description="Registration result")
    s3_endpoint: str = Field(description="S3 server endpoint")
    s3_bucket: str = Field(description="Bucket containing images")
    s3_access_key: str = Field(description="Read-only access key")
    s3_secret_key: str = Field(description="Read-only secret key")
    s3_secure: bool = Field(default=False, description="Use HTTPS for S3")
    s3_region: str | None = Field(default=None, description="S3 region")


class DisplayCommand(BaseModel):
    """Command sent to device to control the display."""

    action: Literal["display", "clear", "status"] = Field(description="Command action")
    image_path: str | None = Field(default=None, description="S3 object path for display action")
    image_id: str | None = Field(default=None, description="Image UUID for tracking")
    title: str | None = Field(default=None, description="Image title for device logging")


class DeviceAcknowledge(BaseModel):
    """Acknowledgment sent by device after processing a command."""

    device_id: str = Field(description="Device identifier")
    image_id: str | None = Field(default=None, description="Currently displayed image UUID")
    successful_display_change: bool = Field(description="Whether the display change was successful")
    error: str | None = Field(default=None, description="Error message if any")
