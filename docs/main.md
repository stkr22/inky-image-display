# Inky Image Display — Architecture

Four components work together to display images on Inky e-ink displays.

## Components

### API (`inky-image-display-api`)

FastAPI service running at `:8000`. Responsibilities:

- **Device registry**: Devices register over HTTP at `POST /api/devices/register` with their display specs (dimensions, orientation, model). The API stores these in the `devices` table and returns the S3 reader credentials.
- **Image library**: Images are stored as metadata in the `images` table and as files in S3-compatible storage.
- **Sync job management**: CRUD REST API for `immich_sync_jobs` records which drive the Sync service.
- **Display control**: REST endpoints publish commands (display, clear) to connected devices over MQTT. A background rotation loop also periodically advances the displayed image.
- **Online tracking**: The API subscribes to retained MQTT status topics. Devices publish `online` on connect and configure an MQTT Last-Will-and-Testament with `offline`, so the broker announces unexpected disconnects automatically.

On startup the API auto-creates the `devices`, `images`, and `immich_sync_jobs` tables and connects to the MQTT broker.

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

CLI tool (`immich-sync`) intended to be run as a cron job. For each active `ImmichSyncJob` record it:

1. Reads the target device's display dimensions from the `devices` table.
2. Queries Immich using the job's filter criteria (albums, people, tags, dates, etc.).
3. Filters results client-side by orientation, minimum color score, and vibrancy score.
4. Downloads, resizes, and stores qualifying images to S3.
5. Persists image metadata to the `images` table.
6. Enforces the `max_images` cap and `retention_days` expiry by deleting old Immich-sourced images.

## Data flow

```
Immich ──(sync)──► S3 Storage ◄──(fetch)── Controller (Raspberry Pi)
                        │
                   API (images table)
                        │
                   devices table ◄──(HTTP register)── Controller
                        │
                   MQTT broker ──(cmd / ack / status)──► Controller
```

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
