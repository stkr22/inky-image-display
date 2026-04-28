"""Configuration management using pydantic-settings."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """UI service settings loaded from environment variables.

    All fields are prefixed with ``UI_`` (e.g. ``UI_API_BASE_URL``).
    """

    model_config = SettingsConfigDict(env_prefix="UI_")

    api_base_url: str
    api_timeout_seconds: float = 30.0

    s3_endpoint: str
    s3_bucket: str = "inky-images"
    s3_secure: bool = False
    s3_region: str | None = None
    s3_reader_access_key: str
    s3_reader_secret_key: str

    host: str = "0.0.0.0"
    port: int = 8080
    root_path: str = ""

    media_cache_max_age: int = 86400

    # Required by NiceGUI's app.storage.tab to sign session cookies.
    storage_secret: str = "inky-image-display-ui-dev-secret"

    @field_validator("api_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        """Remove any trailing slash from the configured API base URL."""
        return value.rstrip("/")
