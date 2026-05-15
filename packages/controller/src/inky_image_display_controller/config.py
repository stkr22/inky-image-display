"""Configuration management using pydantic-settings.

The controller only configures three things locally: its own identity,
how to reach the API for the one-shot registration call, and the
display hardware. MQTT broker parameters and S3 credentials arrive in
the registration response so they stay centrally managed by the API.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeviceConfig(BaseSettings):
    """Device identification settings."""

    id: str = Field(default="inky-display", description="Unique device identifier")
    room: str | None = Field(default=None, description="Room where device is located")


class APIConfig(BaseSettings):
    """API HTTP server connection settings.

    Used for the one-shot registration call. All ongoing device traffic
    (commands, acknowledgements, status) goes through MQTT, whose
    connection details are returned by ``/register``.
    """

    url: str = Field(default="http://localhost:8000", description="API base URL (http:// or https://)")


class DisplayConfig(BaseSettings):
    """Display hardware settings."""

    orientation: Literal["landscape", "portrait"] = Field(default="landscape", description="Display orientation")
    saturation: float = Field(default=0.5, ge=0.0, le=1.0, description="Color saturation for Spectra 6")
    mock: bool = Field(default=False, description="Use mock display for testing without hardware")
    # Only used when mock=True — picks the panel dims a seeded profile reports.
    mock_profile_key: str = Field(
        default="inky_impression_13_spectra6",
        description="Seeded device-profile key whose dimensions the mock display should report",
    )


class Settings(BaseSettings):
    """Main application settings aggregating all configuration sections."""

    model_config = SettingsConfigDict(
        env_prefix="CONTROLLER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    device: DeviceConfig = Field(default_factory=DeviceConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)

    config_file: Path | None = Field(default=None, description="Path to YAML configuration file")

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "Settings":
        """Load settings from a YAML configuration file.

        Args:
            yaml_path: Path to the YAML configuration file.

        Returns:
            Settings instance with values from YAML merged with env vars.

        """
        with yaml_path.open() as f:
            yaml_config = yaml.safe_load(f) or {}

        device_config = DeviceConfig(**yaml_config.get("device", {}))
        api_config = APIConfig(**yaml_config.get("api", {}))
        display_config = DisplayConfig(**yaml_config.get("display", {}))

        return cls(
            device=device_config,
            api=api_config,
            display=display_config,
            config_file=yaml_path,
        )


def load_settings(config_path: Path | None = None) -> Settings:
    """Load application settings from config file and environment variables.

    Args:
        config_path: Optional path to YAML configuration file.

    Returns:
        Settings instance with merged configuration.

    """
    if config_path and config_path.exists():
        return Settings.from_yaml(config_path)
    return Settings()
