"""Configuration models for Immich sync operations.

Connection settings are loaded from environment variables.
Sync job configuration is stored in the database (ImmichSyncJob model).
"""

from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class APIClientConfig(BaseSettings):
    """Display API connection settings from environment variables.

    Environment variables:
        DISPLAY_API_BASE_URL: Base URL for the Display API service
        DISPLAY_API_TIMEOUT_SECONDS: Request timeout in seconds (default: 30)
    """

    model_config = SettingsConfigDict(env_prefix="DISPLAY_API_")

    base_url: HttpUrl = Field(description="Base URL for the Display API service")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout")


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
    api_key: str = Field(description="API key for x-api-key header")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")


class S3WriterConfig(BaseSettings):
    """S3-compatible storage configuration with write access for sync operations.

    Separate from S3Config (reader) to use different credentials.

    Environment variables:
        S3_WRITER_ENDPOINT: S3 server endpoint
        S3_WRITER_BUCKET: Target bucket (default: inky-images)
        S3_WRITER_SECURE: Use HTTPS (default: False)
        S3_WRITER_ACCESS_KEY: Access key with write permissions
        S3_WRITER_SECRET_KEY: Secret key with write permissions
        S3_WRITER_REGION: S3 region (default: us-east-1)
    """

    model_config = SettingsConfigDict(env_prefix="S3_WRITER_")

    endpoint: str = Field(description="S3 server endpoint")
    bucket: str = Field(default="inky-images", description="Bucket for image storage")
    secure: bool = Field(default=False, description="Use HTTPS for S3 connection")
    access_key: str = Field(description="Access key with write permissions")
    secret_key: str = Field(description="Secret key with write permissions")
    region: str | None = Field(default=None, description="S3 region (defaults to minio-py built-in)")


class ImmichSyncConfig(BaseSettings):
    """Global sync settings from environment variables.

    Per-job settings (filters, counts, etc.) are stored in ImmichSyncJob table.

    Environment variables:
        IMMICH_STORAGE_PREFIX: S3 path prefix (default: immich)
        IMMICH_SKIP_EXISTING: Skip already synced images (default: True)
        IMMICH_TARGET_WIDTH: Process images to this width
        IMMICH_TARGET_HEIGHT: Process images to this height
        IMMICH_MAX_IMAGES: Maximum total Immich images in database (default: 20, 0=unlimited)
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
    target_width: int | None = Field(
        default=None,
        description="Process images to this width (None = no processing)",
    )
    target_height: int | None = Field(
        default=None,
        description="Process images to this height (None = no processing)",
    )
    max_images: int = Field(
        default=20,
        ge=0,
        description="Maximum total Immich images in database (0 = unlimited)",
    )
    retention_days: int = Field(
        default=7,
        ge=0,
        description="Days to keep Immich images before cleanup (0 = never expire)",
    )


class DeviceRequirements(BaseModel):
    """Display requirements derived from target device.

    ``width``/``height`` are the raster target for image processing -
    these are swapped relative to the device record for portrait panels,
    because the panel driver addresses pixels in its native landscape
    orientation. ``display_width``/``display_height`` remain the device's
    natural (unswapped) dimensions and are what gets recorded against
    synced Image rows so orientation-aware queries work consistently.
    """

    width: int
    height: int
    display_width: int
    display_height: int
    orientation: str  # "landscape" | "portrait" | "square"
    display_model: str | None = None  # e.g., "inky_impression_spectra_6"
