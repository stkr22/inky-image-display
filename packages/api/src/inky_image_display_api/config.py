"""Configuration management using pydantic-settings."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API service settings loaded from environment variables.

    All fields are prefixed with ``API_`` (e.g. ``API_DATABASE_PATH``).
    """

    model_config = SettingsConfigDict(env_prefix="API_")

    database_path: str

    @property
    def database_url(self) -> str:
        """Construct async SQLite database URL from path.

        Prepends ``sqlite+aiosqlite:///`` to the configured path.
        Absolute paths (starting with ``/``) produce four leading slashes
        in the URL, which is the correct SQLite URI convention.
        """
        return f"sqlite+aiosqlite:///{self.database_path}"

    s3_endpoint: str
    s3_bucket: str = "inky-images"
    s3_secure: bool = False
    s3_writer_access_key: str
    s3_writer_secret_key: str
    s3_region: str | None = None
    s3_reader_access_key: str
    s3_reader_secret_key: str
    default_display_duration: int = 3600

    # MQTT broker — the API's own connection to the broker (server-side).
    # Typically an internal/cluster address with no TLS or websockets.
    mqtt_host: str
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    mqtt_transport: Literal["tcp", "websockets"] = "tcp"
    mqtt_websocket_path: str = "/mqtt"
    mqtt_client_id: str = "inky-api"
    mqtt_keep_alive: int = 30

    # MQTT broker — what controllers receive in the registration response.
    # Typically the public/ingress address (e.g. WSS via HTTPS ingress) and
    # often a different ACL-restricted user than the API itself uses.
    device_mqtt_host: str
    device_mqtt_port: int = 1883
    device_mqtt_username: str | None = None
    device_mqtt_password: SecretStr | None = None
    device_mqtt_tls: bool = False
    device_mqtt_transport: Literal["tcp", "websockets"] = "tcp"
    device_mqtt_websocket_path: str = "/mqtt"
    device_mqtt_keep_alive: int = 30

    # Gemini AI image generation. Required only when the /api/images/generate
    # endpoint is exercised — leaving it blank disables on-demand generation.
    gemini_api_key: SecretStr | None = None
