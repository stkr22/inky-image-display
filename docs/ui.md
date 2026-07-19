# Web frontend (`packages/web`)

React single-page app (Vite + TypeScript + React Router + TanStack Query) with a
bento-style design system, served as static files by the API service. It
replaced the earlier NiceGUI UI service; the `/media` image proxy that service
hosted now lives in the API (`packages/api/.../routes/media.py`).

## Sections

The top nav has five sections:

| Path | Purpose |
|------|---------|
| `/images` | Library: browse, search, upload, edit, delete. Filter by source, orientation, grid pool, or rotation status (excluded images get a badge); real pagination ("x–y of N" via the API's `X-Total-Count`); multi-select mode for bulk delete (with a 7-second Undo window before anything is sent) / bulk grid assignment — bulk failures name the affected images. Image detail has an e-ink preview toggle (server-simulated Spectra 6 dither), a per-image hold time, an exclude-from-rotation switch, and a send dialog that offers *every* device — non-matching panels are sent a server-side cover-crop ("cropped to fit") instead of being hidden |
| `/displays` | Upcoming refresh schedule, online device wall with per-device controls (next, pin/unpin, "don't show again" for the current image, schedule, clear), and grid management. Refresh health distinguishes "failed — retrying" (controller self-heals) from "failing — check power" (failure outlived the backoff; likely needs a physical power cycle); failing devices also surface as alerts on the landing page |
| `/grids/{id}` | Grid detail: proportional canvas preview with drag-to-reposition placements (numeric cm inputs remain for precision), confirmation before removing a placement, per-grid image pool with resolution traffic-light badges and an honest truncation note |
| `/jobs` | Tabbed list of Immich and Gemini sync jobs (`?tab=gemini`) with per-job "Last run" summaries (from `/api/sync-runs`) and a "Run now" button that makes the job due for the worker's next poll, plus each job's schedule ("Runs every … · next …"). Create/edit forms live at `/sync-jobs/*` and `/gemini-jobs/*`. Immich filters use name-based pickers backed by the API's `/api/immich/*` browse proxy when configured |
| `/genai` | Tabbed GenAI hub (`?tab=jobs\|prompts`; old `?tab=motd` links redirect). *Images*: on-demand generation form and a "Recent generations" status list (backed by `GET /api/genai/tasks`, shared with job generations). *Display jobs*: job list with per-job story prompt + source mode, target grid with one content part per slot, daily schedule and duration, generate/display/release actions, and a 7-day story history with per-story preview and redisplay (see [motd.md](motd.md)). *Prompt library*: the block/preset library both other tabs build image prompts from |
| `/settings` | Global default refresh interval, quiet hours (daily window pausing automatic rotation), guest invites |

Legacy deep links (`/generate`, `/prompts`, bare `/sync-jobs`,
`/gemini-jobs`) redirect to their new homes. A dark mode toggle in the nav persists per browser
and defaults to the OS preference. A global error boundary catches render
crashes with a reload prompt instead of a blank page, and the image
detail/upload forms guard unsaved changes on navigation (data-router
blocker + `beforeunload`).

## Architecture

```
Browser ──HTTP──► API container ──S3──► MinIO / Garage (writer credentials)
   ▲                  │
   └── static React   └── MQTT ──► devices
       bundle + /media proxy
```

- The browser talks **same-origin only**: `/api/*` for data, `/media/*` for
  images, everything else falls back to the SPA's `index.html`.
- `/media/{object_key}` streams originals with ETag/Cache-Control;
  `?w=240|480|960` serves a downscaled JPEG generated lazily on first request
  and cached in the bucket under `thumbs/w{width}/…`. Gallery and device-card
  views request `?w=480`; detail views load originals.
- Auth is optional (see [auth.md](auth.md)): unconfigured, the app is open
  (trusted LAN); with OIDC configured the SPA shows a sign-in gate, learns
  its role from `GET /api/auth/me`, and renders a reduced UI (Images +
  GenAI) for guests arriving via invite links. The browser never holds
  tokens — only an HttpOnly session cookie, which also authenticates
  `/media/*` image loads.

## Development

```bash
cd packages/web
npm install
npm run dev        # Vite dev server on :5173, proxying /api and /media to localhost:8000
npm run build      # typecheck + production bundle into dist/
```

Point a locally running API at the build output with
`API_WEB_DIST_PATH=$(pwd)/packages/web/dist`. The API container image builds
and bundles the frontend automatically.
