# Inky Image Display — Architecture

Three components work together to display images on Inky e-ink displays.

## Components

### API (`inky-image-display-api`)

FastAPI service running at `:8000`. Responsibilities:

- **Device registry**: Devices connect via WebSocket at `/ws/devices/{device_id}` and register with their display specs (dimensions, orientation, model). The API stores these in the `devices` table.
- **Image library**: Images are stored as metadata in the `images` table and as files in S3-compatible storage.
- **Sync job management**: CRUD REST API for `immich_sync_jobs` records which drive the Sync service.
- **Display control**: REST endpoints push commands (display, clear) to connected devices via the WebSocket connection. A background rotation loop also periodically advances the displayed image.

On startup the API auto-creates the `devices`, `images`, and `immich_sync_jobs` tables.

### Controller (`inky-image-display-controller`)

Python daemon that runs on the Raspberry Pi hosting an Inky display. It:

1. Connects to the API WebSocket and sends a `DeviceRegistration` message (device ID, room, display specs).
2. Receives a `RegistrationResponse` containing S3 reader credentials.
3. Waits for `DisplayCommand` messages pushed by the API.
4. Fetches the image file from S3, resizes/crops to the display's exact pixel dimensions, and calls the Inky library to refresh the screen.
5. Sends a `DeviceAcknowledge` back to the API after each command.

Reconnects automatically with exponential backoff if the WebSocket drops.

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
                   devices table ◄──(register)── Controller
                        │
                   REST / WebSocket ──(command)──► Controller
```

## MQTT topics (controller ↔ display)

Communication between the API and Controller is over WebSocket (not MQTT). The controller subscribes to a single WebSocket connection per device.

| Direction | Message type | Description |
|-----------|-------------|-------------|
| Controller → API | `DeviceRegistration` | Sent once on connect; declares display specs |
| API → Controller | `RegistrationResponse` | S3 credentials + confirmation status |
| API → Controller | `DisplayCommand` | `display` (with image path), `clear`, or `status` |
| Controller → API | `DeviceAcknowledge` | Success/failure result for each command |
