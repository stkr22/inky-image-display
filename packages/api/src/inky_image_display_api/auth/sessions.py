"""Signed-cookie sessions and guest-invite tokens.

Both ride on itsdangerous with the same secret but distinct salts, so a
guest-invite token can never be replayed as a session cookie. Sessions are
signed (tamper-proof) but not encrypted — they only carry role/sub/name,
never secrets.
"""

from __future__ import annotations

import time
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE = "inky_session"

_SESSION_SALT = "inky-session"
_INVITE_SALT = "inky-guest-invite"


def load_session(secret: str, cookie_value: str, max_age_seconds: int) -> dict[str, Any]:
    """Return the session payload, or an empty dict for invalid/expired input.

    Expiry is enforced twice: the itsdangerous timestamp bounds any cookie at
    the admin TTL, while the embedded ``exp`` lets shorter-lived roles (guest)
    expire earlier than the cookie signature would.
    """
    serializer = URLSafeTimedSerializer(secret, salt=_SESSION_SALT)
    try:
        data = serializer.loads(cookie_value, max_age=max_age_seconds)
    except BadSignature:
        return {}
    if not isinstance(data, dict):
        return {}
    exp = data.get("exp")
    if isinstance(exp, int | float) and exp < time.time():
        return {}
    return data


def dump_session(secret: str, session: dict[str, Any]) -> str:
    """Serialize and sign a session payload for the cookie value."""
    return URLSafeTimedSerializer(secret, salt=_SESSION_SALT).dumps(session)


def create_guest_invite(secret: str) -> str:
    """Mint a guest-invite token; expiry rides on the itsdangerous timestamp."""
    return URLSafeTimedSerializer(secret, salt=_INVITE_SALT).dumps({"v": 1})


def verify_guest_invite(secret: str, token: str, max_age_seconds: int) -> bool:
    """Check an invite token's signature and age."""
    serializer = URLSafeTimedSerializer(secret, salt=_INVITE_SALT)
    try:
        serializer.loads(token, max_age=max_age_seconds)
    except BadSignature:
        return False
    return True
