"""Inky Display Controller - E-ink display management for Raspberry Pi.

This package provides a daemon that registers with the inky-image-display
API over HTTP, then receives display commands over MQTT and renders
images on an Inky Impression e-ink display.
"""

__version__ = "4.1.0"

from inky_image_display_shared.schemas import (
    DeviceAcknowledge,
    DeviceRegistration,
    DisplayCommand,
    RegistrationResponse,
)

from inky_image_display_controller.config import Settings, load_settings
from inky_image_display_controller.controller import DisplayController
from inky_image_display_controller.exceptions import (
    CommunicationError,
    ConfigurationError,
    DisplayControllerError,
    DisplayError,
)

__all__ = [
    "CommunicationError",
    "ConfigurationError",
    "DeviceAcknowledge",
    "DeviceRegistration",
    "DisplayCommand",
    "DisplayController",
    "DisplayControllerError",
    "DisplayError",
    "RegistrationResponse",
    "Settings",
    "__version__",
    "load_settings",
]
