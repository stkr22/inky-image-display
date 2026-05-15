"""Command and response schemas for device communication.

These models define the contract between the API and device controllers.
The same payloads ride MQTT for command/ack/status traffic and the
HTTP ``/api/devices/register`` endpoint for the initial handshake.
"""

from typing import Literal

from pydantic import BaseModel, Field


class DeviceRegistration(BaseModel):
    """Device registration payload.

    Sent by the device on startup to announce itself. The controller does
    not send raw panel dimensions — those live on the device profile that
    matches ``device_profile_key``.
    """

    device_id: str = Field(description="Unique device identifier")
    device_profile_key: str = Field(
        description="Stable key of the device profile (e.g. 'inky_impression_13_spectra6')",
    )
    orientation: Literal["landscape", "portrait"] = Field(
        default="landscape",
        description="Mounted orientation of the panel",
    )
    room: str | None = Field(default=None, description="Room where device is located")


class RegistrationResponse(BaseModel):
    """Response sent after successful device registration.

    Carries everything the controller needs to talk to the rest of the
    system: S3 read credentials for image fetches and the MQTT broker
    parameters for command/ack/status traffic. The controller only
    needs local config for its own identity, display hardware, and
    where to find this API.
    """

    status: Literal["registered", "updated"] = Field(description="Registration result")
    s3_endpoint: str = Field(description="S3 server endpoint")
    s3_bucket: str = Field(description="Bucket containing images")
    s3_access_key: str = Field(description="Read-only access key")
    s3_secret_key: str = Field(description="Read-only secret key")
    s3_secure: bool = Field(default=False, description="Use HTTPS for S3")
    s3_region: str | None = Field(default=None, description="S3 region")
    mqtt_host: str = Field(description="MQTT broker hostname")
    mqtt_port: int = Field(default=1883, description="MQTT broker port")
    mqtt_username: str | None = Field(default=None, description="MQTT username")
    mqtt_password: str | None = Field(default=None, description="MQTT password")
    mqtt_tls: bool = Field(default=False, description="Use TLS for the broker connection")
    mqtt_transport: Literal["tcp", "websockets"] = Field(
        default="tcp",
        description="MQTT transport. Use 'websockets' to tunnel via HTTP(S) ingress.",
    )
    mqtt_websocket_path: str = Field(
        default="/mqtt",
        description="HTTP path served by the broker for MQTT-over-WebSockets",
    )
    mqtt_keep_alive: int = Field(default=30, description="MQTT keep-alive in seconds")


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


class DeviceStatus(BaseModel):
    """Online/offline status published to a retained MQTT topic.

    Devices publish ``online`` on connect and configure an MQTT
    Last-Will-and-Testament with ``offline`` so the broker announces
    unexpected disconnects on the same retained topic.
    """

    status: Literal["online", "offline"] = Field(description="Current device status")
