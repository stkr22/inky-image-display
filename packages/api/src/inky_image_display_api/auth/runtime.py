"""Resolved auth configuration.

A plain dataclass (not ``Settings``) so the middleware and routes depend on
explicit, already-validated values — tests construct it directly without
faking the whole settings object.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inky_image_display_api.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthRuntime:
    """Auth values the request path needs, resolved once at startup."""

    enabled: bool
    session_secret: str
    cookie_secure: bool
    admin_session_ttl_seconds: int
    guest_session_ttl_seconds: int
    guest_invite_ttl_seconds: int
    sync_token: str | None
    device_token: str | None
    public_base_url: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> AuthRuntime:
        """Build the runtime from environment settings.

        A missing session secret gets a random per-process value so the
        guest-link feature works out of the box; the warning matters because
        every restart then invalidates sessions and pending invites.
        """
        if settings.session_secret is not None:
            session_secret = settings.session_secret.get_secret_value()
        else:
            session_secret = secrets.token_urlsafe(32)
            logger.warning(
                "API_SESSION_SECRET is not set - using an ephemeral secret; "
                "sessions and guest invites will not survive a restart"
            )
        if settings.auth_enabled and not settings.public_base_url:
            msg = "API_PUBLIC_BASE_URL is required when OIDC auth is enabled (builds the redirect URI)"
            raise ValueError(msg)
        return cls(
            enabled=settings.auth_enabled,
            session_secret=session_secret,
            cookie_secure=settings.cookie_secure,
            admin_session_ttl_seconds=settings.admin_session_ttl_minutes * 60,
            guest_session_ttl_seconds=settings.guest_session_ttl_minutes * 60,
            guest_invite_ttl_seconds=settings.guest_invite_ttl_minutes * 60,
            sync_token=settings.sync_token.get_secret_value() if settings.sync_token else None,
            device_token=settings.device_token.get_secret_value() if settings.device_token else None,
            public_base_url=settings.public_base_url.rstrip("/") if settings.public_base_url else None,
        )
