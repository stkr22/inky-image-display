# Inky Image Display — Architecture

Four components work together to display images on Inky e-ink displays.

## Components

### API (`inky-image-display-api`)

FastAPI service running at `:8000`. Responsibilities:

- **Device registry**: Devices register over HTTP at `POST /api/devices/register` with their `device_profile_key` (one of the seeded Inky lineup, e.g. `inky_impression_13_spectra6`) and mounted orientation. The API stores the device with a FK to the matching `device_profiles` row and returns the S3 reader credentials.
- **Device profiles**: `/api/device-profiles` exposes a fixed lineup of supported panels (4" / 7.3" / 13.3" Spectra 6) seeded by migration. One row is marked `is_default` and feeds the genai default-target dropdown; name is editable from the UI, panel dims/model are immutable.
- **Image library**: Images are stored as metadata in the `images` table and as files in S3-compatible storage. List responses carry an `X-Total-Count` header for real pagination. Per-image curation flags: `excluded_from_rotation` (operator veto — never picked automatically, manual sends still work) and an optional `display_duration_seconds` hold that overrides the device interval while that image is up.
- **E-ink render preview**: `GET /api/images/{id}/eink-preview` (and a `POST /api/images/eink-preview` twin for not-yet-uploaded bytes) returns a PNG simulating the Spectra 6 panel rendering — the same saturation-blended palette + Floyd-Steinberg dither the Inky driver applies on-device — so operators see the six-ink result before a 30-second refresh burns it onto the wall. Results are cached under `thumbs/eink/` in the bucket.
- **Sync job management**: CRUD REST API for `immich_sync_jobs` records which drive the Sync service. Each job carries its own schedule (`interval_minutes`, `next_run_at`) so cadence is set in the UI, not in deployment cron specs: the worker runs on one frequent cron and calls `POST /api/sync-jobs/claim-due` (and the Gemini twin), which hands out due jobs and advances their schedules. `POST /api/sync-jobs/{id}/run-now` makes a job due immediately (active or not), and `POST/GET /api/sync-runs` is where workers report per-run outcomes (shown as "Last run" in the UI; pruned to ~20 rows per job) — the report also clears the run-now flag and stamps `last_run_at`.
- **AI generation**: `/api/genai/*` endpoints expose the prompt library (blocks + presets), Gemini batch jobs, and on-demand generation. `POST /api/genai/generate` runs the Gemini call in a FastAPI background task and pushes the result to a matching online device over MQTT as soon as it's ready — no polling. Task status lives in the `generation_tasks` table (bounded, pruned on insert), so `GET /api/genai/tasks` history survives API restarts.
- **Display control**: REST endpoints publish commands (display, clear) to connected devices over MQTT. Manual sends validate pixel dimensions: an exact match sends as-is, `fit="auto"` cover-crops a derived copy to the panel size server-side (cached under `derived/` in the bucket), and a mismatch without auto-fit is rejected with 409 — the controller cannot rescale and would ack a failure. A background rotation loop periodically advances the displayed image: candidates are the 5 least-recently-shown compatible images with a random pick among them (LRU fairness without replaying the identical sequence every cycle). Devices can be **pinned** (hold the current image; rotation skips them) and a global **quiet hours** window (app settings) pauses automatic rotation daily — manual pushes and display-job schedules are unaffected. Refresh-health transitions can push a notification to `API_NOTIFY_URL` (ntfy-style).
- **Grids**: `/api/grids/*` groups devices into a shared physical canvas so they jointly display slices of a larger image. Grids are defined as a tile layout (rows of devices); the canvas size and every cm placement are computed from the device profiles' physical dimensions, and each placement carries a stable slot address (`row`/`col`). The API pre-renders per-device crops to S3 and pushes ordinary display commands; controllers need no grid-aware code. See [grids.md](grids.md).
- **Display jobs**: `/api/display-jobs/*` are content generators that target a grid — the MOTD (daily positive story generated with Gemini, optionally grounded in Google Search) is the first job type. Jobs use the same external-worker claim model as the sync jobs: the worker claims due jobs, generates exact-size screens for the grid's slots, and registers them as an image group targeting the grid. *When* the content shows is the grid's business: groups and pool images flow through one content queue per grid, and the grid's daily display schedule front-runs the queue with the newest generated group. Release resumes the queue immediately with a jittered next refresh so panels don't flash in lockstep. A single display participates by living in a one-panel grid. See [motd.md](motd.md).
- **Online tracking**: The API subscribes to retained MQTT status topics. Devices publish `online` on connect and configure an MQTT Last-Will-and-Testament with `offline`, so the broker announces unexpected disconnects automatically.

On startup the API auto-creates the `device_profiles`, `devices`, `images`, `grids`, `grid_devices`, `immich_sync_jobs`, `prompt_blocks`, `prompt_presets`, `gemini_sync_jobs`, `display_jobs`, `display_job_slots`, and `motd_*` tables, applies any pending Alembic migrations (the AI tables get seeded with a default prompt library on first run; `device_profiles` gets the three-panel Inky Impression Spectra 6 lineup plus physical-area dimensions used by grids), and connects to the MQTT broker.

### Controller (`inky-image-display-controller`)

Python daemon that runs on the Raspberry Pi hosting an Inky display. It:

1. Calls `POST /api/devices/register` over HTTP and receives a `RegistrationResponse` containing S3 reader credentials.
2. Connects to the MQTT broker, publishes a retained `online` status to `inky/devices/{device_id}/status`, and subscribes to `inky/devices/{device_id}/cmd`.
3. Receives `DisplayCommand` messages, fetches the image from S3, resizes/crops to the display's exact pixel dimensions, and calls the Inky library to refresh the screen.
4. Publishes a `DeviceAcknowledge` to `inky/devices/{device_id}/ack` after each command.

Reconnects automatically with exponential backoff if MQTT drops.

### Web frontend (`packages/web`)

React single-page app (Vite + TypeScript) served as static files by the API (`API_WEB_DIST_PATH`). Lets an operator browse, upload, and edit images, command devices (display next, pick a specific image, clear), manage grids and sync jobs, and trigger on-demand AI generation. Images reach the browser via the API's `/media/{object_key:path}` proxy (with lazy `?w=` thumbnails cached in S3), so the browser never talks to S3 directly. Authentication is optional: with an OIDC issuer configured the API enforces sign-in for humans, machine tokens for the sync jobs and controllers, and signed invite links for guests; unconfigured it stays open (trusted LAN only). See [auth.md](auth.md) and [ui.md](ui.md).

### Sync (`inky-image-display-sync`)

CLI with two subcommands, both intended to run from a single frequent cron
(e.g. every minute). By default each invocation claims *due* jobs from the
API — jobs whose stored `interval_minutes` schedule has elapsed, or that were
flagged with the UI's "Run now" button — and exits immediately when nothing
is due, so the frequent cron stays cheap. `--all` ignores the schedule and
runs every active job (manual/debug); `--dry-run` previews without claiming.

**`inky-image-display-sync immich`** (default) — for each due `ImmichSyncJob`:

1. Reads the target panel dimensions from the job's `target_device_profile_id` (and the job's optional `orientation` override).
2. Queries Immich using the job's filter criteria (albums, people, tags, dates, etc.).
3. Filters results client-side by orientation, minimum color score, and vibrancy score.
4. Downloads, resizes, and stores qualifying images to S3.
5. Persists image metadata to the `images` table.
6. Enforces each job's `max_images` cap (counted against only that job's own uploads) and the `retention_days` expiry by deleting old Immich-sourced images.

After each job run (either subcommand), the worker POSTs a run report to `/api/sync-runs` — status, images added/skipped/deleted, errors — which the UI surfaces per job and which clears the job's "Run now" flag (see [configuration.md](configuration.md)).

**`inky-image-display-sync gemini`** — for each due `GeminiSyncJob`:

1. Resolves the job's `prompt_preset_id` (which carries the model name and the five prompt blocks) via the API.
2. Iterates `subjects × images_per_subject`, calling the configured Gemini image model.
3. Stores results in S3 under `gemini/{uuid}.jpg` and registers them with `source_name="gemini"`. Optional `retention_days` lets the API clean up later.

Both subcommands share the same `DisplayAPIClient` (subclassed per source for the source-specific endpoints) and the same `ImageProcessor`/`ColorProfileAnalyzer` helpers.

## Data flow

```
Immich        ──(immich-sync, cron)──┐
Gemini batch  ──(gemini-sync, cron)──┤
UI POST /api/genai/generate (background task) ──► S3 Storage ◄──(fetch)── Controller (Raspberry Pi)
                                                       │
                                                  API (images table)
                                                       │
                                                  devices table ◄──(HTTP register)── Controller
                                                       │
                                                  MQTT broker ──(cmd / ack / status)──► Controller
```

On-demand generation: the UI's "Generate an image" form posts to `POST /api/genai/generate` with a subject, optional `target_device_profile_id` (defaults to the `is_default` profile), preset, and orientation. The API queues a background task that calls Gemini, uploads the JPEG to S3, registers the row, and (when `push_immediately` is true) picks a *random* online device whose `device_profile_id` and `display_orientation` both match the request, then publishes a display command over MQTT. If no matching device is online the image is persisted but no command is sent — it'll show up in the next rotation when a matching device reconnects.

## MQTT topics (API ↔ Controller)

All device traffic flows through an external MQTT broker. The API
subscribes once to status and ack topics with single-level wildcards;
the controller subscribes only to its own command topic.

| Topic | Direction | QoS | Retain | Payload |
|-------|-----------|-----|--------|---------|
| `inky/devices/{id}/status` | Controller → broker | 1 | yes | `DeviceStatus` (`online` / `offline` — `offline` also set as MQTT Last-Will) |
| `inky/devices/{id}/cmd` | API → Controller | 1 | no | `DisplayCommand` (`display` with image path, `clear`, or `status`) |
| `inky/devices/{id}/ack` | Controller → API | 1 | no | `DeviceAcknowledge` (success/failure for each command) |

Initial registration uses HTTP (`POST /api/devices/register`) and returns
`RegistrationResponse` with S3 reader credentials. This is a one-shot
call on startup — all ongoing communication is over MQTT.
