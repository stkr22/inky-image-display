"""Tests for sessions, guest invites, machine tokens and the access policy."""

import base64
import time
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from inky_image_display_api.auth import (
    AuthRuntime,
    Principal,
    check_access,
    create_guest_invite,
    dump_session,
    load_session,
    resolve_principal,
    verify_guest_invite,
)
from inky_image_display_api.auth.policy import origin_rejected
from inky_image_display_api.auth.sessions import SESSION_COOKIE
from inky_image_display_shared.models import DeviceProfile
from inky_image_display_shared.schemas import DeviceRegistration

SECRET = "test-secret"


def make_runtime(**overrides) -> AuthRuntime:
    base = AuthRuntime(
        enabled=True,
        session_secret=SECRET,
        cookie_secure=False,
        admin_session_ttl_seconds=3600,
        guest_session_ttl_seconds=1800,
        guest_invite_ttl_seconds=600,
        sync_token=None,
        device_token=None,
        public_base_url="https://inky.example.com",
    )
    return replace(base, **overrides)


class TestSessions:
    def test_roundtrip(self):
        payload = {"role": "admin", "sub": "u1", "name": "Alice", "exp": time.time() + 60}
        cookie = dump_session(SECRET, payload)
        assert load_session(SECRET, cookie, 3600) == payload

    def test_tampered_cookie_is_rejected(self):
        cookie = dump_session(SECRET, {"role": "admin"})
        assert load_session(SECRET, cookie + "x", 3600) == {}
        assert load_session("other-secret", cookie, 3600) == {}

    def test_embedded_exp_expires_session(self):
        cookie = dump_session(SECRET, {"role": "guest", "exp": time.time() - 1})
        assert load_session(SECRET, cookie, 3600) == {}

    def test_signature_age_bound(self):
        cookie = dump_session(SECRET, {"role": "admin"})
        assert load_session(SECRET, cookie, -1) == {}


class TestGuestInviteTokens:
    def test_valid_token_verifies(self):
        token = create_guest_invite(SECRET)
        assert verify_guest_invite(SECRET, token, 600)

    def test_wrong_secret_fails(self):
        token = create_guest_invite(SECRET)
        assert not verify_guest_invite("other-secret", token, 600)

    def test_expired_token_fails(self):
        token = create_guest_invite(SECRET)
        assert not verify_guest_invite(SECRET, token, -1)

    def test_invite_token_is_not_a_session_cookie(self):
        # Distinct salts: an invite URL leaking must never double as a
        # session cookie.
        token = create_guest_invite(SECRET)
        assert load_session(SECRET, token, 600) == {}


class TestResolvePrincipal:
    def test_api_key_resolves_machine_principals(self):
        auth = make_runtime(sync_token="sync-key", device_token="device-key")
        assert resolve_principal({}, "sync-key", auth).kind == "sync"
        assert resolve_principal({}, "device-key", auth).kind == "device"

    def test_invalid_api_key_never_falls_back_to_session(self):
        auth = make_runtime(sync_token="sync-key")
        session = {"role": "admin", "name": "Alice"}
        assert resolve_principal(session, "wrong", auth).kind == "anonymous"

    def test_session_roles(self):
        auth = make_runtime()
        assert resolve_principal({"role": "admin", "name": "A"}, None, auth).kind == "admin"
        assert resolve_principal({"role": "guest"}, None, auth).kind == "guest"
        assert resolve_principal({}, None, auth).kind == "anonymous"


class TestAccessPolicy:
    PUBLIC_PATHS = (
        "/health",
        "/auth/login",
        "/auth/callback",
        "/auth/guest",
        "/auth/logout",
        "/api/auth/me",
        "/",
        "/assets/app.js",
    )

    @pytest.mark.parametrize("path", PUBLIC_PATHS)
    def test_public_paths_allow_anonymous(self, path: str):
        auth = make_runtime()
        assert check_access(Principal(kind="anonymous"), "GET", path, auth) is None

    @pytest.mark.parametrize("path", ["/api/images", "/media/foo.jpg", "/api/devices"])
    def test_anonymous_denied_when_enabled(self, path: str):
        auth = make_runtime()
        denial = check_access(Principal(kind="anonymous"), "GET", path, auth)
        assert denial is not None
        assert denial[0] == 401

    def test_anonymous_allowed_when_disabled(self):
        auth = make_runtime(enabled=False)
        assert check_access(Principal(kind="anonymous"), "DELETE", "/api/images/abc", auth) is None

    def test_admin_allows_everything(self):
        auth = make_runtime()
        assert check_access(Principal(kind="admin"), "DELETE", "/api/images/abc", auth) is None

    @pytest.mark.parametrize(
        ("method", "path", "allowed"),
        [
            ("GET", "/media/originals/a.jpg", True),
            ("GET", "/api/images", True),
            ("GET", "/api/images/stats", True),
            ("GET", "/api/images/0a1b2c3d-0000-0000-0000-000000000000", True),
            ("POST", "/api/genai/generate", True),
            ("GET", "/api/genai/tasks", True),
            ("GET", "/api/devices", True),
            ("POST", "/api/devices/kitchen/display", True),
            ("POST", "/api/devices/kitchen/next", True),
            ("DELETE", "/api/images/0a1b2c3d-0000-0000-0000-000000000000", False),
            ("POST", "/api/images", False),
            ("PATCH", "/api/devices/kitchen", False),
            ("POST", "/api/devices/kitchen/clear", False),
            ("PUT", "/api/motd/config", False),
            ("GET", "/api/sync-jobs", False),
            ("POST", "/api/auth/guest-invites", False),
        ],
    )
    def test_guest_allowlist(self, method: str, path: str, allowed: bool):
        auth = make_runtime()
        denial = check_access(Principal(kind="guest"), method, path, auth)
        assert (denial is None) is allowed

    def test_sync_token_scope(self):
        auth = make_runtime(sync_token="sync-key")
        sync = Principal(kind="sync")
        assert check_access(sync, "POST", "/api/images/process", auth) is None
        assert check_access(sync, "GET", "/api/sync-jobs", auth) is None
        assert check_access(sync, "GET", "/media/foo.jpg", auth) is not None

    def test_device_token_scope(self):
        auth = make_runtime(device_token="device-key")
        device = Principal(kind="device")
        assert check_access(device, "POST", "/api/devices/register", auth) is None
        assert check_access(device, "GET", "/api/images", auth) is not None


class TestOriginCheck:
    def test_cross_origin_mutation_rejected(self):
        auth = make_runtime()
        assert origin_rejected(Principal(kind="admin"), "POST", "https://evil.example", "inky.example.com", auth)

    def test_same_host_allowed(self):
        auth = make_runtime()
        assert not origin_rejected(Principal(kind="admin"), "POST", "http://inky.local:8000", "inky.local:8000", auth)

    def test_public_base_url_allowed(self):
        auth = make_runtime()
        assert not origin_rejected(Principal(kind="admin"), "POST", "https://inky.example.com", "internal:8000", auth)

    def test_missing_origin_allowed(self):
        auth = make_runtime()
        assert not origin_rejected(Principal(kind="admin"), "POST", None, "inky.local", auth)

    def test_reads_and_machine_tokens_exempt(self):
        auth = make_runtime()
        assert not origin_rejected(Principal(kind="admin"), "GET", "https://evil.example", "inky.local", auth)
        assert not origin_rejected(Principal(kind="sync"), "POST", "https://evil.example", "inky.local", auth)


def admin_cookie(ttl: int = 3600) -> str:
    return dump_session(SECRET, {"role": "admin", "sub": "u1", "name": "Alice", "exp": time.time() + ttl})


class TestMiddlewareIntegration:
    def test_anonymous_locked_out_when_enabled(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        assert client.get("/api/devices").status_code == 401
        assert client.get("/health").status_code == 200

    def test_me_reports_anonymous_states(self, test_app: FastAPI, client: TestClient):
        # Trusted-LAN mode: anonymous acts as admin.
        body = client.get("/api/auth/me").json()
        assert body == {"auth_enabled": False, "authenticated": False, "role": "admin", "name": None}
        test_app.state.auth = make_runtime()
        body = client.get("/api/auth/me").json()
        assert body == {"auth_enabled": True, "authenticated": False, "role": None, "name": None}

    def test_admin_session_cookie_grants_access(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        client.cookies.set(SESSION_COOKIE, admin_cookie())
        assert client.get("/api/devices").status_code == 200
        body = client.get("/api/auth/me").json()
        assert body["role"] == "admin"
        assert body["name"] == "Alice"

    def test_expired_admin_session_is_anonymous(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        client.cookies.set(SESSION_COOKIE, admin_cookie(ttl=-10))
        assert client.get("/api/devices").status_code == 401

    def test_cross_origin_mutation_rejected(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        client.cookies.set(SESSION_COOKIE, admin_cookie())
        resp = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403


class TestGuestInviteFlow:
    def test_full_flow(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime(public_base_url=None)
        client.cookies.set(SESSION_COOKIE, admin_cookie())

        created = client.post("/api/auth/guest-invites")
        assert created.status_code == 201
        body = created.json()
        assert "/auth/guest?token=" in body["url"]
        assert base64.b64decode(body["qr_png_base64"]).startswith(b"\x89PNG")

        guest = TestClient(test_app)
        token = body["url"].split("token=", 1)[1]
        resp = guest.get(f"/auth/guest?token={token}", follow_redirects=False)
        assert resp.status_code == 303
        assert SESSION_COOKIE in guest.cookies

        me = guest.get("/api/auth/me").json()
        assert me["role"] == "guest"
        assert guest.get("/api/images").status_code == 200
        assert guest.post("/api/genai/generate", json={}).status_code != 403
        assert guest.get("/api/sync-jobs").status_code == 403
        assert guest.delete("/api/images/00000000-0000-0000-0000-000000000000").status_code == 403
        assert guest.post("/api/auth/guest-invites").status_code == 403

        assert guest.post("/auth/logout").status_code == 204
        assert guest.get("/api/auth/me").json()["role"] is None

    def test_invalid_token_rejected(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        resp = client.get("/auth/guest?token=garbage", follow_redirects=False)
        assert resp.status_code == 403
        resp = client.get("/auth/guest", follow_redirects=False)
        assert resp.status_code == 403

    def test_guest_invites_require_admin(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        assert client.post("/api/auth/guest-invites").status_code == 401

    def test_admin_scanning_invite_keeps_admin_session(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime()
        client.cookies.set(SESSION_COOKIE, admin_cookie())
        token = create_guest_invite(SECRET)
        resp = client.get(f"/auth/guest?token={token}", follow_redirects=False)
        assert resp.status_code == 303
        assert client.get("/api/auth/me").json()["role"] == "admin"


class TestMachineTokens:
    def test_sync_token_grants_api_access(self, test_app: FastAPI, client: TestClient):
        test_app.state.auth = make_runtime(sync_token="sync-key")
        assert client.get("/api/images", headers={"x-api-key": "sync-key"}).status_code == 200
        assert client.get("/api/images", headers={"x-api-key": "wrong"}).status_code == 401

    async def test_device_token_only_registers(self, test_app: FastAPI, seed_profile: DeviceProfile):
        test_app.state.auth = make_runtime(device_token="device-key")
        registration = DeviceRegistration(
            device_id="party-display",
            device_profile_key=seed_profile.key,
            orientation="landscape",
        )
        with TestClient(test_app) as client:
            headers = {"x-api-key": "device-key"}
            resp = client.post("/api/devices/register", json=registration.model_dump(mode="json"), headers=headers)
            assert resp.status_code == 200
            assert client.get("/api/images", headers=headers).status_code == 403
