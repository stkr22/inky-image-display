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

    # Browser-facing media proxy (/media/*): Cache-Control max-age for
    # originals and thumbnails.
    media_cache_max_age: int = 86400

    # Directory holding the built React frontend (packages/web/dist). When
    # set, the API serves it with an SPA fallback; when unset the API is
    # headless and the frontend must be hosted elsewhere.
    web_dist_path: str | None = None

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

    # Immich browsing proxy (/api/immich/*). Optional: when unset, the UI
    # falls back to free-text ID inputs for sync-job filters. Use the same
    # values the sync service is configured with.
    immich_base_url: str | None = None
    immich_api_key: SecretStr | None = None
    immich_timeout_seconds: float = 20.0

    # --- Authentication (docs/auth.md) ---
    # Human auth is OIDC (authorization code + PKCE) handled server-side:
    # the API is the OIDC client and the browser only ever holds a signed
    # HttpOnly session cookie. Auth enforcement is off until both
    # ``oidc_issuer`` and ``oidc_client_id`` are set, preserving the
    # historical trusted-LAN behaviour for existing deployments.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    # Optional: leave unset for a public client (PKCE only), which is the
    # recommended Zitadel app type for this deployment.
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: str = "openid profile email"

    # External base URL of the deployment (e.g. https://inky.example.com).
    # Needed to build the OIDC redirect URI and guest-invite links; required
    # when OIDC is enabled.
    public_base_url: str | None = None

    # Signs session cookies and guest-invite tokens. When unset a random
    # per-process secret is used, which invalidates sessions and pending
    # invites on every restart — fine for trying things out, set it in
    # production.
    session_secret: SecretStr | None = None
    # Secure flag on the session cookie. Unset: inferred from
    # ``public_base_url`` (https → secure) so plain-HTTP LAN setups keep
    # working without configuration.
    session_cookie_secure: bool | None = None
    admin_session_ttl_minutes: int = 43200  # 30 days
    guest_session_ttl_minutes: int = 1440  # 24 hours
    guest_invite_ttl_minutes: int = 720  # 12 hours

    # Internal machine tokens (x-api-key header). Deliberately not Zitadel
    # service users: both callers are cluster-internal and a static secret
    # keeps them free of token refresh and clock concerns. Two separate
    # tokens so they can be rotated independently and scoped — the sync
    # token gets full API access, the device token only unlocks
    # POST /api/devices/register. Only enforced while OIDC auth is enabled.
    # (Field names combine with env_prefix to API_SYNC_TOKEN /
    # API_DEVICE_TOKEN — keep them in sync with docs and the Helm chart.)
    sync_token: SecretStr | None = None
    device_token: SecretStr | None = None

    @property
    def auth_enabled(self) -> bool:
        """Whether request authentication is enforced."""
        return bool(self.oidc_issuer and self.oidc_client_id)

    @property
    def cookie_secure(self) -> bool:
        """Effective Secure flag for the session cookie."""
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return bool(self.public_base_url and self.public_base_url.startswith("https://"))
