# Authentication

Auth is **off by default**: without an OIDC issuer configured the API keeps
its historical trusted-LAN behaviour and everything works exactly as before.
Setting `API_OIDC_ISSUER` + `API_OIDC_CLIENT_ID` turns enforcement on for
every request to `/api/*` and `/media/*` (`/health`, the `/auth/*` endpoints
and the static SPA shell stay public).

There are three kinds of callers, each with its own mechanism:

| Caller | Mechanism | Why |
|--------|-----------|-----|
| Humans (operator) | OIDC authorization code + PKCE against Zitadel, handled server-side (BFF) | Browser only ever holds an HttpOnly session cookie — no tokens in JS, and `<img src="/media/...">` requests authenticate automatically |
| Party guests | Signed invite link / QR code minted in the UI | No IdP account or login screen on a guest's phone; the session is restricted and short-lived |
| Machines (sync worker, display controllers) | Static internal tokens in an `x-api-key` header | Cluster-internal callers; a static secret avoids token refresh/clock concerns and keeps Zitadel for humans only |

## Human sign-in (OIDC, backend-for-frontend)

The API itself is the OIDC client. `GET /auth/login` redirects to the
issuer (authorization code + PKCE), `GET /auth/callback` exchanges the code
server-side and sets a signed, HttpOnly, `SameSite=Lax` session cookie.
The SPA never sees a token; it learns its role from `GET /api/auth/me`.

Every OIDC-authenticated user becomes **admin** — this is a single-user
app, and *who may sign in at all* is controlled in Zitadel (only grant the
project/app to your own user). Sessions last `API_ADMIN_SESSION_TTL_MINUTES`
(default 30 days); `POST /auth/logout` clears the cookie locally.

### Zitadel setup

1. Create a project and, inside it, an application of type **Web** with
   authentication method **PKCE** (public client — no client secret needed).
   For a confidential client instead, set `API_OIDC_CLIENT_SECRET`.
2. Redirect URI: `https://<your-host>/auth/callback`.
3. Configure the API:

```bash
API_OIDC_ISSUER=https://zitadel.example.com
API_OIDC_CLIENT_ID=<client id>
API_PUBLIC_BASE_URL=https://inky.example.com
API_SESSION_SECRET=<long random string>   # e.g. openssl rand -base64 48
```

## Guest access (signed invite links)

Admins mint an invite on the **Settings** page ("Guest access" → *Create
invite link*). The result is a URL of the form `/auth/guest?token=...` plus
a QR code — put the QR on the table and every guest who scans it gets a
**guest session** (default 24 h) without touching the IdP. Invite tokens
are multi-use and expire after `API_GUEST_INVITE_TTL_MINUTES` (default 12 h).

Guests can browse images, use GenAI generation and push a result to a
display; they cannot upload, delete, or touch devices, jobs, grids, display jobs or
settings. The allowlist lives in
`packages/api/src/inky_image_display_api/auth/policy.py`.

Invite tokens and session cookies are signed with `API_SESSION_SECRET`
(distinct salts, so an invite can never be replayed as a session cookie).

## Machine tokens

Two independent static tokens, both sent as `x-api-key` and only enforced
while OIDC auth is enabled:

- `API_SYNC_TOKEN` — full API access for the sync worker. Configure the
  same value as `DISPLAY_API_TOKEN` on the sync side.
- `API_DEVICE_TOKEN` — grants **only** `POST /api/devices/register` (the
  endpoint that hands out S3 reader and MQTT credentials). Configure the
  same value as `CONTROLLER_API__TOKEN` (or `api.token` in the controller's
  YAML) on each device.

Two tokens instead of one so they can be rotated independently and a leaked
device token cannot read or mutate anything beyond registration.

## Kubernetes (Helm chart)

Create a Secret and reference it, then enable OIDC via values:

```bash
kubectl create secret generic inky-auth \
  --from-literal=session-secret="$(openssl rand -base64 48)" \
  --from-literal=sync-token="$(openssl rand -base64 32)" \
  --from-literal=device-token="$(openssl rand -base64 32)"
```

```yaml
config:
  auth:
    oidcIssuer: https://zitadel.example.com
    oidcClientId: "123456789"
    publicBaseUrl: https://inky.example.com
existingSecrets:
  auth: inky-auth
```

The chart injects the sync token into the sync worker automatically.
Controllers are configured out-of-band (their YAML/env), so set
`CONTROLLER_API__TOKEN` on each device.

## Behaviour matrix

| Request | Auth disabled | Auth enabled |
|---------|---------------|--------------|
| Anonymous browser → `/api/*`, `/media/*` | allowed (trusted LAN) | 401 → SPA shows sign-in |
| OIDC session cookie | n/a | full access |
| Guest session cookie | restricted to the guest allowlist | restricted to the guest allowlist |
| `x-api-key: <sync token>` | allowed (header ignored) | full `/api/*` access |
| `x-api-key: <device token>` | allowed (header ignored) | `POST /api/devices/register` only |
| `/health`, `/auth/*`, SPA static files | public | public |

Note that guest restrictions apply whenever a guest cookie is present, even
with auth disabled — but in that mode an anonymous request has full access,
so guest links only meaningfully confine guests once OIDC is enabled.

## CSRF and cookie properties

The session cookie is HttpOnly, `SameSite=Lax`, and `Secure` when
`API_PUBLIC_BASE_URL` is https (override with `API_SESSION_COOKIE_SECURE`).
On top of SameSite, mutating requests carrying a session cookie are
rejected when their `Origin` header doesn't match the request host or
`API_PUBLIC_BASE_URL`. Machine tokens are immune to CSRF by construction
(a foreign page cannot set an `x-api-key` header).
