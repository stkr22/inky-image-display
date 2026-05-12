"""Gemini sync service configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GeminiConnectionConfig(BaseSettings):
    """Gemini API credentials.

    Environment variable: ``GEMINI_API_KEY``.
    """

    model_config = SettingsConfigDict(env_prefix="GEMINI_")

    api_key: str = Field(description="API key for the Google Generative AI SDK")


class GeminiSyncConfig(BaseSettings):
    """Global Gemini sync settings.

    Per-job settings (subjects, count, orientation) live in the
    ``gemini_sync_jobs`` table.
    """

    model_config = SettingsConfigDict(env_prefix="GEMINI_SYNC_")

    storage_prefix: str = Field(default="gemini", description="S3 path prefix for generated images")
