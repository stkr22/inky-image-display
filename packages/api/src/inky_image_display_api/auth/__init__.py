"""Authentication: OIDC (human), signed guest links, internal machine tokens.

See docs/auth.md for the full design. The pieces:

- ``runtime``: resolved auth configuration stored on ``app.state.auth``.
- ``sessions``: signed session-cookie and guest-invite token helpers.
- ``policy``: request principals and the method/path access policy.
- ``middleware``: single ASGI middleware that loads the session, resolves
  the principal and enforces the policy for every request.
"""

from inky_image_display_api.auth.middleware import SessionAuthMiddleware
from inky_image_display_api.auth.policy import Principal, check_access, resolve_principal
from inky_image_display_api.auth.runtime import AuthRuntime
from inky_image_display_api.auth.sessions import (
    create_guest_invite,
    dump_session,
    load_session,
    verify_guest_invite,
)

__all__ = [
    "AuthRuntime",
    "Principal",
    "SessionAuthMiddleware",
    "check_access",
    "create_guest_invite",
    "dump_session",
    "load_session",
    "resolve_principal",
    "verify_guest_invite",
]
