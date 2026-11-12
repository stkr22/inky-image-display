"""Configuration models for Immich sync operations.

Connection settings are loaded from environment variables.
Sync job configuration is stored in the database (ImmichSyncJob model).
"""

from pydantic import BaseModel, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class APIClientConfig(BaseSettings):
    """Display API connection settings from environment variables.

    Environment variables:
        DISPLAY_API_BASE_URL: Base URL for the Display API service
        DISPLAY_API_TIMEOUT_SECONDS: Request timeout in seconds (default: 30)
        DISPLAY_API_TOKEN: Machine token (x-api-key) — the API's
            API_SYNC_TOKEN. Required once the API enforces auth.
    """

    model_config = SettingsConfigDict(env_prefix="DISPLAY_API_")

    base_url: HttpUrl = Field(description="Base URL for the Display API service")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout")
    token: SecretStr | None = Field(default=None, description="Machine token sent as x-api-key header")


class ImmichConnectionConfig(BaseSettings):
    """Immich server connection settings from environment variables.

    Environment variables:
        IMMICH_BASE_URL: Immich server URL
        IMMICH_API_KEY: API key for authentication
        IMMICH_TIMEOUT_SECONDS: Request timeout (default: 30)
        IMMICH_VERIFY_SSL: Verify SSL certificates (default: True)
    """

    model_config = SettingsConfigDict(env_prefix="IMMICH_")

    base_url: HttpUrl = Field(description="Immich server base URL")
    # SecretStr keeps the key out of reprs and accidental log lines.
    api_key: SecretStr = Field(description="API key for x-api-key header")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")


class ImmichSyncConfig(BaseSettings):
    """Global sync settings from environment variables.

    Per-job settings (filters, counts, etc.) are stored in ImmichSyncJob table.

    Environment variables:
        IMMICH_STORAGE_PREFIX: S3 path prefix (default: immich)
        IMMICH_SKIP_EXISTING: Skip already synced images (default: True)
        IMMICH_TARGET_WIDTH: Process images to this width
        IMMICH_TARGET_HEIGHT: Process images to this height
    """

    model_config = SettingsConfigDict(env_prefix="IMMICH_")

    storage_prefix: str = Field(
        default="immich",
        description="S3 path prefix for stored images",
    )
    skip_existing: bool = Field(
        default=True,
        description="Skip images already in database",
    )
    retention_days: int = Field(
        default=7,
        ge=0,
        description="Days to keep Immich images before cleanup (0 = never expire)",
    )


class DeviceRequirements(BaseModel):
    """Display requirements derived from target device.

    ``width``/``height`` are the orientation-aware raster target: narrow-first
    for portrait devices (the device row stores panel-native landscape dims,
    so these are swapped for portrait). Used both as the resize/crop target
    and as what gets recorded against synced Image rows.
    """

    width: int
    height: int
    orientation: str  # "landscape" | "portrait" | "square"
