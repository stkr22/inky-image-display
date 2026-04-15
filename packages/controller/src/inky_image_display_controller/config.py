"""Configuration management using pydantic-settings."""

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
    """API server connection settings."""

    url: str = Field(default="ws://localhost:8000", description="API base URL (ws:// or wss://)")
    reconnect_interval: int = Field(default=5, description="Initial reconnect delay in seconds")
    max_reconnect_interval: int = Field(default=60, description="Maximum reconnect delay")


class S3Config(BaseSettings):
    """S3-compatible object storage connection settings.

    These are typically populated from the registration response,
    but can be pre-configured via environment variables.
    """

    endpoint: str = Field(default="localhost:9000", description="S3 server endpoint")
    bucket: str = Field(default="inky-images", description="Bucket containing images")
    access_key: str | None = Field(default=None, description="S3 access key")
    secret_key: str | None = Field(default=None, description="S3 secret key")
    secure: bool = Field(default=False, description="Use HTTPS for S3 connection")


class DisplayConfig(BaseSettings):
    """Display hardware settings."""

    orientation: Literal["landscape", "portrait"] = Field(default="landscape", description="Display orientation")
    saturation: float = Field(default=0.5, ge=0.0, le=1.0, description="Color saturation for Spectra 6")
    mock: bool = Field(default=False, description="Use mock display for testing without hardware")
    # Only used when mock=True (no hardware to query)
    mock_width: int = Field(default=1600, gt=0, description="Mock display width in pixels")
    mock_height: int = Field(default=1200, gt=0, description="Mock display height in pixels")


class Settings(BaseSettings):
    """Main application settings aggregating all configuration sections."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="ignore",
    )

    device: DeviceConfig = Field(default_factory=DeviceConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    s3: S3Config = Field(default_factory=S3Config)
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

        # Build nested config from YAML
        device_config = DeviceConfig(**yaml_config.get("device", {}))
        api_config = APIConfig(**yaml_config.get("api", {}))
        s3_config = S3Config(**yaml_config.get("s3", {}))
        display_config = DisplayConfig(**yaml_config.get("display", {}))

        return cls(
            device=device_config,
            api=api_config,
            s3=s3_config,
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
