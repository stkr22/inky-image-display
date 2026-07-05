"""OIDC client construction (authlib, authorization code + PKCE).

The API is the OIDC client (backend-for-frontend): the code exchange happens
server-side and the browser only ever receives the signed session cookie.
Metadata is fetched lazily from the issuer's discovery document on first
login, so startup has no network dependency on the IdP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from authlib.integrations.starlette_client import OAuth

if TYPE_CHECKING:
    from inky_image_display_api.config import Settings

OIDC_CLIENT_NAME = "oidc"


def build_oauth(settings: Settings) -> OAuth:
    """Register the OIDC client from settings; call only when auth is enabled."""
    if not settings.oidc_issuer or not settings.oidc_client_id:
        msg = "OIDC issuer and client id must be configured"
        raise ValueError(msg)
    client_kwargs: dict[str, str] = {
        "scope": settings.oidc_scopes,
        "code_challenge_method": "S256",
    }
    client_secret = settings.oidc_client_secret.get_secret_value() if settings.oidc_client_secret else None
    if client_secret is None:
        # Public client (recommended Zitadel app type here): PKCE alone
        # protects the exchange, no client authentication at the token
        # endpoint.
        client_kwargs["token_endpoint_auth_method"] = "none"
    oauth = OAuth()
    oauth.register(
        name=OIDC_CLIENT_NAME,
        server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=client_secret,
        client_kwargs=client_kwargs,
    )
    return oauth
