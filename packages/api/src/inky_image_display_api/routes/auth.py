"""Auth endpoints: OIDC sign-in (BFF), guest invites, session info.

Human sign-in is the standard authorization-code + PKCE dance with the
session kept server-signed in an HttpOnly cookie. Guest access skips the
IdP entirely: an admin mints a short-lived signed link (rendered as a QR
code) and anyone opening it gets a restricted guest session — party guests
never see a Zitadel login screen.
"""

from __future__ import annotations

import base64
import io
import time
from datetime import UTC, datetime, timedelta

import qrcode
from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from inky_image_display_api.auth import create_guest_invite, verify_guest_invite
from inky_image_display_api.auth.oidc import OIDC_CLIENT_NAME
from inky_image_display_api.schemas import AuthMeResponse, GuestInviteResponse

router = APIRouter(tags=["auth"])

_INVALID_INVITE_PAGE = """<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Invite expired</title></head>
<body style="font-family: system-ui, sans-serif; display: grid; place-items: center;
             min-height: 90vh; text-align: center;">
<div><h1>This invite link is invalid or has expired</h1>
<p>Ask your host for a fresh QR code.</p></div>
</body></html>"""


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request) -> Response:
    """Start the OIDC redirect dance; no-op redirect when auth is disabled."""
    auth = request.app.state.auth
    if not auth.enabled:
        return RedirectResponse("/", status_code=303)
    client = getattr(request.app.state.oauth, OIDC_CLIENT_NAME)
    redirect_uri = f"{auth.public_base_url}/auth/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", include_in_schema=False)
async def callback(request: Request) -> Response:
    """Exchange the authorization code and establish the admin session.

    Every OIDC-authenticated user becomes admin: this is a single-user app
    and *who* may sign in is controlled in Zitadel (project authorization),
    not here. Guests come through signed invite links instead.
    """
    auth = request.app.state.auth
    if not auth.enabled:
        return RedirectResponse("/", status_code=303)
    client = getattr(request.app.state.oauth, OIDC_CLIENT_NAME)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=f"OIDC sign-in failed: {exc.error}") from exc
    userinfo = token.get("userinfo") or await client.userinfo(token=token)
    name = userinfo.get("name") or userinfo.get("preferred_username") or userinfo.get("email")
    request.session.clear()
    request.session.update(
        {
            "role": "admin",
            "sub": userinfo.get("sub"),
            "name": name,
            "exp": time.time() + auth.admin_session_ttl_seconds,
        }
    )
    return RedirectResponse("/", status_code=303)


@router.get("/auth/guest", include_in_schema=False)
async def guest_signin(request: Request, token: str = "") -> Response:
    """Turn a valid invite token into a guest session and enter the app."""
    auth = request.app.state.auth
    if not token or not verify_guest_invite(auth.session_secret, token, auth.guest_invite_ttl_seconds):
        return HTMLResponse(_INVALID_INVITE_PAGE, status_code=403)
    if request.session.get("role") == "admin":
        # The admin scanning their own QR must not downgrade themselves.
        return RedirectResponse("/", status_code=303)
    request.session.clear()
    request.session.update(
        {
            "role": "guest",
            "name": "Guest",
            "exp": time.time() + auth.guest_session_ttl_seconds,
        }
    )
    return RedirectResponse("/", status_code=303)


@router.post("/auth/logout", status_code=204, include_in_schema=False)
async def logout(request: Request) -> Response:
    """Clear the local session (no IdP round-trip needed for this app)."""
    request.session.clear()
    return Response(status_code=204)


@router.get("/api/auth/me", response_model=AuthMeResponse)
async def me(request: Request) -> AuthMeResponse:
    """Report the effective session so the SPA can gate and shape its UI."""
    auth = request.app.state.auth
    principal = request.state.principal
    if principal.kind in ("admin", "guest"):
        return AuthMeResponse(
            auth_enabled=auth.enabled,
            authenticated=True,
            role=principal.kind,
            name=principal.name,
        )
    # Anonymous: full access while auth is disabled (trusted LAN), locked
    # out once it is enabled.
    return AuthMeResponse(
        auth_enabled=auth.enabled,
        authenticated=False,
        role=None if auth.enabled else "admin",
        name=None,
    )


@router.post("/api/auth/guest-invites", response_model=GuestInviteResponse, status_code=201)
async def create_guest_invite_link(request: Request) -> GuestInviteResponse:
    """Mint a guest invite link (admin only, enforced by the middleware).

    Tokens are multi-use within their TTL on purpose: one QR code on the
    table serves every guest at the party.
    """
    auth = request.app.state.auth
    token = create_guest_invite(auth.session_secret)
    base = auth.public_base_url or str(request.base_url).rstrip("/")
    url = f"{base}/auth/guest?token={token}"
    expires_at = datetime.now(UTC) + timedelta(seconds=auth.guest_invite_ttl_seconds)
    return GuestInviteResponse(url=url, expires_at=expires_at, qr_png_base64=_qr_png_base64(url))


def _qr_png_base64(url: str) -> str:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image().get_image()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()
