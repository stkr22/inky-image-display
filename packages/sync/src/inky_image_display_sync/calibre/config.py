"""Configuration for the Calibre OPDS book source.

Connection settings come from environment variables; what gets generated from
the books is per-job configuration like the other sources.
"""

from typing import Self

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CalibreConnectionConfig(BaseSettings):
    """Calibre OPDS connection settings from environment variables.

    Environment variables:
        CALIBRE_BASE_URL: Base URL of the server serving OPDS
        CALIBRE_TIMEOUT_SECONDS: Request timeout (default: 30)
        CALIBRE_VERIFY_SSL: Verify SSL certificates (default: True)
        CALIBRE_CACHE_TTL_SECONDS: How long the paged catalog stays cached
            (default: 6 hours)
        CALIBRE_USERNAME / CALIBRE_PASSWORD: HTTP basic-auth credentials for
            servers that disable anonymous browsing (Calibre-Web Automated).
            Both or neither; unset keeps requests unauthenticated.
    """

    model_config = SettingsConfigDict(env_prefix="CALIBRE_")

    base_url: HttpUrl = Field(description="Base URL of the server serving the OPDS catalog")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    # Reading the whole library costs one request per 60 books, and a home
    # library changes far more slowly than display jobs run.
    cache_ttl_seconds: int = Field(default=21600, ge=0, description="Catalog cache lifetime in seconds")
    # OIDC users have no password, so OPDS basic auth needs a local account on
    # the server. A SecretStr keeps the password out of reprs and log lines.
    username: str | None = Field(default=None, min_length=1, description="OPDS basic-auth username")
    password: SecretStr | None = Field(default=None, description="OPDS basic-auth password")

    @model_validator(mode="after")
    def _credentials_are_a_pair(self) -> Self:
        # Half a pair would silently fall back to anonymous requests and
        # surface later as an unexplained 401, so fail at startup instead.
        if (self.username is None) != (self.password is None):
            raise ValueError("CALIBRE_USERNAME and CALIBRE_PASSWORD must be set together")
        return self
