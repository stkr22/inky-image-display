"""Request principals and the access policy.

The policy lives in one method/path table instead of per-route dependencies
because the existing routes use ``request.app.state`` rather than ``Depends``
— a central table keeps enforcement auditable in a single place and lets the
guest role split read from write within a router.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from inky_image_display_api.auth.runtime import AuthRuntime

PrincipalKind = Literal["admin", "guest", "sync", "device", "anonymous"]

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# What a party guest needs and nothing more: browse images, generate via
# GenAI, and push a result to a display. Everything else stays admin-only.
_GUEST_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GET", re.compile(r"^/media/.+$")),
    ("GET", re.compile(r"^/api/images$")),
    ("GET", re.compile(r"^/api/images/stats$")),
    ("GET", re.compile(r"^/api/images/[0-9a-fA-F-]+$")),
    ("GET", re.compile(r"^/api/images/[0-9a-fA-F-]+/eink-preview$")),
    ("POST", re.compile(r"^/api/genai/generate$")),
    ("GET", re.compile(r"^/api/genai/tasks$")),
    ("GET", re.compile(r"^/api/genai/blocks$")),
    ("GET", re.compile(r"^/api/genai/presets$")),
    ("GET", re.compile(r"^/api/devices$")),
    ("POST", re.compile(r"^/api/devices/[^/]+/(display|next)$")),
)


@dataclass(frozen=True)
class Principal:
    """Who is making the request, resolved once per request."""

    kind: PrincipalKind
    name: str | None = None
    sub: str | None = None


def resolve_principal(session: dict[str, Any], api_key: str | None, auth: AuthRuntime) -> Principal:
    """Map an x-api-key header or session payload to a principal.

    A presented-but-invalid API key resolves to anonymous rather than
    falling through to the cookie, so a bad machine token can never ride
    on an ambient browser session.
    """
    if api_key:
        if auth.sync_token and secrets.compare_digest(api_key, auth.sync_token):
            return Principal(kind="sync", name="sync-service")
        if auth.device_token and secrets.compare_digest(api_key, auth.device_token):
            return Principal(kind="device", name="device")
        return Principal(kind="anonymous")
    role = session.get("role")
    if role == "admin":
        return Principal(kind="admin", name=session.get("name"), sub=session.get("sub"))
    if role == "guest":
        return Principal(kind="guest", name=session.get("name") or "Guest")
    return Principal(kind="anonymous")


def check_access(principal: Principal, method: str, path: str, auth: AuthRuntime) -> tuple[int, str] | None:
    """Return None when allowed, else (status_code, detail).

    Anonymous access is only denied while OIDC auth is enabled — with auth
    unconfigured the app keeps its historical trusted-LAN behaviour, and
    guest sessions still restrict whoever holds a guest cookie.
    """
    if _is_public(path) or principal.kind == "admin":
        return None
    if principal.kind == "sync":
        is_api = path == "/api" or path.startswith("/api/")
        return None if is_api else (403, "Sync token only grants API access")
    if principal.kind == "device":
        is_register = method == "POST" and path == "/api/devices/register"
        return None if is_register else (403, "Device token only grants device registration")
    if principal.kind == "guest":
        allowed = any(method == m and pattern.match(path) for m, pattern in _GUEST_RULES)
        return None if allowed else (403, "Guest access does not permit this action")
    return None if not auth.enabled else (401, "Authentication required")


def origin_rejected(principal: Principal, method: str, origin: str | None, host: str | None, auth: AuthRuntime) -> bool:
    """CSRF defence-in-depth on top of SameSite=Lax cookies.

    Only cookie-derived principals are at risk (machine tokens live in a
    header an attacker's page cannot set). A missing Origin header is
    accepted — non-browser clients and same-origin GETs don't send one.
    """
    if principal.kind not in ("admin", "guest") or method not in _MUTATING_METHODS:
        return False
    if not origin or origin == "null":
        return origin == "null"
    origin_host = re.sub(r"^https?://", "", origin).rstrip("/")
    if host and origin_host == host:
        return False
    if auth.public_base_url:
        public_host = re.sub(r"^https?://", "", auth.public_base_url).rstrip("/")
        if origin_host == public_host:
            return False
    return True


def _is_public(path: str) -> bool:
    """Paths that never require a principal.

    Everything outside /api and /media is the static SPA shell — it holds
    no data, and gating it would break the sign-in page itself.
    """
    if path == "/health":
        return True
    # /auth/logout is public so a guest session can end itself.
    if path in ("/auth/login", "/auth/callback", "/auth/guest", "/auth/logout"):
        return True
    if path == "/api/auth/me":
        return True
    is_protected = path in ("/api", "/media") or path.startswith(("/api/", "/media/"))
    return not is_protected
