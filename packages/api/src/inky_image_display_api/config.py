"""Configuration management using pydantic-settings."""

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

    # MQTT broker — used for command/ack/status traffic with devices.
    mqtt_host: str
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    mqtt_client_id: str = "inky-api"
    mqtt_keep_alive: int = 30
