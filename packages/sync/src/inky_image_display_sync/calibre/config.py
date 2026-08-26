"""Configuration for the Calibre-Web book source.

Connection settings come from environment variables; what gets generated from
the books is per-job configuration like the other sources.
"""

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class CalibreConnectionConfig(BaseSettings):
    """Calibre-Web connection settings from environment variables.

    Environment variables:
        CALIBRE_BASE_URL: Calibre-Web base URL
        CALIBRE_TIMEOUT_SECONDS: Request timeout (default: 30)
        CALIBRE_VERIFY_SSL: Verify SSL certificates (default: True)
        CALIBRE_CACHE_TTL_SECONDS: How long the paged catalog stays cached
            (default: 6 hours)
    """

    model_config = SettingsConfigDict(env_prefix="CALIBRE_")

    base_url: HttpUrl = Field(description="Calibre-Web base URL serving the OPDS catalog")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    # Reading the whole library costs one request per 60 books, and a home
    # library changes far more slowly than display jobs run.
    cache_ttl_seconds: int = Field(default=21600, ge=0, description="Catalog cache lifetime in seconds")
