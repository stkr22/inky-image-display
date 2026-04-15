"""Configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API service settings loaded from environment variables.

    All fields are prefixed with ``API_`` (e.g. ``API_DATABASE_URL``).
    """

    model_config = SettingsConfigDict(env_prefix="API_")

    database_url: str
    s3_endpoint: str
    s3_bucket: str = "inky-images"
    s3_secure: bool = False
    s3_writer_access_key: str
    s3_writer_secret_key: str
    s3_region: str | None = None
    s3_reader_access_key: str
    s3_reader_secret_key: str
    default_display_duration: int = 3600
