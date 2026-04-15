"""Custom exception hierarchy for the display controller."""


class DisplayControllerError(Exception):
    """Base exception for all display controller errors."""


class ConfigurationError(DisplayControllerError):
    """Raised when configuration is invalid or missing."""


class CommunicationError(DisplayControllerError):
    """Raised when MQTT or S3 communication fails."""


class DisplayError(DisplayControllerError):
    """Raised when a display hardware operation fails."""
