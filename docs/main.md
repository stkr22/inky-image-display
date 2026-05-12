# Inky Image Display — Architecture

Four components work together to display images on Inky e-ink displays.

## Components

### API (`inky-image-display-api`)

FastAPI service running at `:8000`. Responsibilities:

- **Device registry**: Devices register over HTTP at `POST /api/devices/register` with their display specs (dimensions, orientation, model). The API stores these in the `devices` table and returns the S3 reader credentials.
- **Image library**: Images are stored as metadata in the `images` table and as files in S3-compatible storage.
- **Sync job management**: CRUD REST API for `immich_sync_jobs` records which drive the Sync service.
- **AI generation**: `/api/genai/*` endpoints expose the prompt library (blocks + presets), Gemini batch jobs, and on-demand generation. `POST /api/genai/generate` runs the Gemini call in a FastAPI background task and pushes the result to a matching online device over MQTT as soon as it's ready — no polling.
- **Display control**: REST endpoints publish commands (display, clear) to connected devices over MQTT. A background rotation loop also periodically advances the displayed image.
- **Online tracking**: The API subscribes to retained MQTT status topics. Devices publish `online` on connect and configure an MQTT Last-Will-and-Testament with `offline`, so the broker announces unexpected disconnects automatically.

On startup the API auto-creates the `devices`, `images`, `immich_sync_jobs`, `prompt_blocks`, `prompt_presets`, and `gemini_sync_jobs` tables, applies any pending Alembic migrations (the AI tables get seeded with a default prompt library on first run), and connects to the MQTT broker.

### Controller (`inky-image-display-controller`)

Python daemon that runs on the Raspberry Pi hosting an Inky display. It:

1. Calls `POST /api/devices/register` over HTTP and receives a `RegistrationResponse` containing S3 reader credentials.
2. Connects to the MQTT broker, publishes a retained `online` status to `inky/devices/{device_id}/status`, and subscribes to `inky/devices/{device_id}/cmd`.
3. Receives `DisplayCommand` messages, fetches the image from S3, resizes/crops to the display's exact pixel dimensions, and calls the Inky library to refresh the screen.
4. Publishes a `DeviceAcknowledge` to `inky/devices/{device_id}/ack` after each command.

Reconnects automatically with exponential backoff if MQTT drops.

### UI (`inky-image-display-ui`)

Flet-based web UI mounted inside a FastAPI app. Lets an operator browse, upload, and edit images, command devices (display next, pick a specific image, clear), and manage sync jobs. Images are proxied to the browser via a `/media/{object_key:path}` route using reader S3 credentials, so the browser never talks to S3 directly. No authentication — trusted LAN only. See [ui.md](ui.md).

### Sync (`inky-image-display-sync`)

CLI with two subcommands, both intended to run as cron jobs:

**`inky-image-display-sync immich`** (default) — for each active `ImmichSyncJob`:

1. Reads the target device's display dimensions from the `devices` table.
2. Queries Immich using the job's filter criteria (albums, people, tags, dates, etc.).
3. Filters results client-side by orientation, minimum color score, and vibrancy score.
4. Downloads, resizes, and stores qualifying images to S3.
5. Persists image metadata to the `images` table.
6. Enforces the `max_images` cap and `retention_days` expiry by deleting old Immich-sourced images.

**`inky-image-display-sync gemini`** — for each active `GeminiSyncJob`:

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

On-demand generation: the UI's "Generate an image" form posts to `POST /api/genai/generate` with a subject, target device, preset, and orientation flag. The API queues a background task that calls Gemini, uploads the JPEG to S3, registers the row, and (when `push_immediately` is true and the device is online) immediately publishes a display command over MQTT — there's no separate worker process.

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
