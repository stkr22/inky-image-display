"""Session + auth enforcement as one ASGI middleware.

Deliberately not Starlette's ``SessionMiddleware``: that needs the secret at
``add_middleware`` time, but this app constructs ``Settings`` in the lifespan
so importing ``main`` stays environment-free. This middleware reads the
resolved ``AuthRuntime`` from ``app.state`` per request instead, and provides
``scope["session"]`` so authlib's Starlette integration works unchanged.

Pure ASGI (no ``BaseHTTPMiddleware``) keeps the streaming /media hot path
free of response buffering.
"""

from __future__ import annotations

from http import cookies as http_cookies
from typing import TYPE_CHECKING

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from inky_image_display_api.auth.policy import check_access, origin_rejected, resolve_principal
from inky_image_display_api.auth.sessions import SESSION_COOKIE, dump_session, load_session

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from inky_image_display_api.auth.runtime import AuthRuntime


class SessionAuthMiddleware:
    """Load the signed session cookie, resolve the principal, enforce policy."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the downstream ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one request: session in, policy check, cookie out."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        auth: AuthRuntime = scope["app"].state.auth
        headers = Headers(scope=scope)

        session = self._load_session(headers, auth)
        scope["session"] = session
        # Snapshot for change detection: routes mutate the dict in place and
        # the cookie is only (re)written when the content actually changed.
        initial_session = dict(session)

        principal = resolve_principal(session, headers.get("x-api-key"), auth)
        scope.setdefault("state", {})["principal"] = principal

        method: str = scope["method"]
        path: str = scope["path"]

        denial = check_access(principal, method, path, auth)
        if denial is not None:
            status_code, detail = denial
            await JSONResponse({"detail": detail}, status_code=status_code)(scope, receive, send)
            return
        if origin_rejected(principal, method, headers.get("origin"), headers.get("host"), auth):
            await JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)(scope, receive, send)
            return

        async def send_with_session(message: Message) -> None:
            if message["type"] == "http.response.start" and scope["session"] != initial_session:
                response_headers = MutableHeaders(scope=message)
                response_headers.append("set-cookie", self._session_cookie(scope["session"], auth))
            await send(message)

        await self.app(scope, receive, send_with_session)

    @staticmethod
    def _load_session(headers: Headers, auth: AuthRuntime) -> dict:
        raw = headers.get("cookie")
        if not raw:
            return {}
        parsed = http_cookies.SimpleCookie()
        try:
            parsed.load(raw)
        except http_cookies.CookieError:
            return {}
        morsel = parsed.get(SESSION_COOKIE)
        if morsel is None:
            return {}
        return load_session(auth.session_secret, morsel.value, auth.admin_session_ttl_seconds)

    @staticmethod
    def _session_cookie(session: dict, auth: AuthRuntime) -> str:
        if session:
            value = dump_session(auth.session_secret, session)
            max_age = auth.admin_session_ttl_seconds
        else:
            value = ""
            max_age = 0
        cookie = f"{SESSION_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
        if auth.cookie_secure:
            cookie += "; Secure"
        return cookie
