# Configuration

All configuration is via environment variables. The controller additionally supports a YAML file for structured settings.

## API (`inky-image-display-api`)

All variables are prefixed with `API_`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_DATABASE_PATH` | Yes | — | Path to the SQLite database file, e.g. `/data/inky.db` |
| `API_S3_ENDPOINT` | Yes | — | S3 endpoint, e.g. `garage.storage.svc:3900` |
| `API_S3_WRITER_ACCESS_KEY` | Yes | — | Write-access S3 key (for image upload) |
| `API_S3_WRITER_SECRET_KEY` | Yes | — | Write-access S3 secret |
| `API_S3_READER_ACCESS_KEY` | Yes | — | Read-only S3 key (sent to controllers on registration) |
| `API_S3_READER_SECRET_KEY` | Yes | — | Read-only S3 secret |
| `API_S3_BUCKET` | No | `inky-images` | S3 bucket name |
| `API_S3_SECURE` | No | `false` | Use HTTPS for S3 |
| `API_S3_REGION` | No | — | S3 region (omit for MinIO/Garage) |
| `API_DEFAULT_DISPLAY_DURATION` | No | `3600` | Default image display duration (seconds) |
| `API_MQTT_HOST` | Yes | — | MQTT broker hostname |
| `API_MQTT_PORT` | No | `1883` | MQTT broker port |
| `API_MQTT_USERNAME` | No | — | MQTT username |
| `API_MQTT_PASSWORD` | No | — | MQTT password |
| `API_MQTT_TLS` | No | `false` | Use TLS for the broker connection |
| `API_MQTT_TRANSPORT` | No | `tcp` | `tcp` or `websockets` (use ws to tunnel via HTTP(S) ingress) |
| `API_MQTT_WEBSOCKET_PATH` | No | `/mqtt` | HTTP path the broker serves WS on (when `transport=websockets`) |
| `API_MQTT_CLIENT_ID` | No | `inky-api` | MQTT client identifier |
| `API_MQTT_KEEP_ALIVE` | No | `30` | MQTT keep-alive interval (seconds) |
| `API_GEMINI_API_KEY` | No | — | Google Generative AI key. Required only for `POST /api/genai/generate`; leave unset to disable on-demand generation (returns 503). |

### MQTT transport / TLS combinations

`tls` and `transport` are independent. The four combinations map to:

| `tls` | `transport` | Effective URL | Typical port | Use when |
|-------|-------------|---------------|--------------|----------|
| `false` | `tcp` | `mqtt://`  | `1883` | LAN broker, no TLS (dev / trusted network) |
| `true`  | `tcp` | `mqtts://` | `8883` | Dedicated MQTT VIP with its own cert |
| `false` | `websockets` | `ws://`  | `8080`/`9001` | Behind a plaintext reverse proxy (rare) |
| `true`  | `websockets` | `wss://` | `443` | Broker behind your existing HTTPS Ingress (recommended for K8s) |

The same settings are sent to controllers in the registration
response, so they do not need to be reconfigured per device.

## UI (`inky-image-display-ui`)

All variables are prefixed with `UI_`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UI_API_BASE_URL` | Yes | — | Base URL of the API, e.g. `http://api.svc:8000` |
| `UI_API_TIMEOUT_SECONDS` | No | `30` | HTTP request timeout when calling the API |
| `UI_S3_ENDPOINT` | Yes | — | S3 endpoint, e.g. `garage.storage.svc:3900` |
| `UI_S3_READER_ACCESS_KEY` | Yes | — | Read-only S3 key (used by the `/media` proxy) |
| `UI_S3_READER_SECRET_KEY` | Yes | — | Read-only S3 secret |
| `UI_S3_BUCKET` | No | `inky-images` | S3 bucket name |
| `UI_S3_SECURE` | No | `false` | Use HTTPS for S3 |
| `UI_S3_REGION` | No | — | S3 region (omit for MinIO/Garage) |
| `UI_HOST` | No | `0.0.0.0` | Bind address |
| `UI_PORT` | No | `8001` | Listen port |
| `UI_ROOT_PATH` | No | `""` | Reverse-proxy sub-path (e.g. `/ui`) |
| `UI_MEDIA_CACHE_MAX_AGE` | No | `86400` | `Cache-Control: max-age` for `/media` responses |

## Controller (`inky-image-display-controller`)

The controller only configures three things locally: its own identity, the API URL for the one-shot registration call, and the display hardware. MQTT broker parameters and S3 read credentials are returned by `POST /api/devices/register` so the API stays the single source of truth for fleet-wide settings.

The controller supports both a YAML file and environment variables. Environment variables are prefixed with `CONTROLLER_` and take precedence; nested fields use `__` as a delimiter (e.g. `CONTROLLER_DEVICE__ID`).

### YAML configuration file

Pass the file path with `--config /path/to/config.yaml` or `-c`.

```yaml
device:
  id: inky-kitchen          # Unique device identifier
  room: Kitchen             # Optional room label

api:
  url: http://api.local:8000  # API base URL (used for one-shot HTTP registration)

display:
  orientation: landscape    # "landscape" or "portrait"
  saturation: 0.5           # Spectra 6 color saturation (0.0–1.0)
  mock: false               # true = no hardware required (for testing)
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTROLLER_DEVICE__ID` | `inky-display` | Device identifier |
| `CONTROLLER_DEVICE__ROOM` | — | Room label |
| `CONTROLLER_API__URL` | `http://localhost:8000` | API base URL (HTTP registration only) |
| `CONTROLLER_DISPLAY__ORIENTATION` | `landscape` | `landscape` or `portrait` |
| `CONTROLLER_DISPLAY__SATURATION` | `0.5` | Color saturation for Spectra 6 (0.0–1.0) |
| `CONTROLLER_DISPLAY__MOCK` | `false` | Use mock display (no hardware) |
| `CONTROLLER_DISPLAY__MOCK_WIDTH` | `1600` | Mock display width (pixels) |
| `CONTROLLER_DISPLAY__MOCK_HEIGHT` | `1200` | Mock display height (pixels) |
| `DEVICE_ID` | — | Overrides `CONTROLLER_DEVICE__ID` (also accepted as `--device-id` CLI flag) |

## Sync (`inky-image-display-sync`)

### Display API connection

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISPLAY_API_BASE_URL` | Yes | — | Base URL of the Display API, e.g. `http://api.svc:8000` |
| `DISPLAY_API_TIMEOUT_SECONDS` | No | `30` | HTTP request timeout |

### Immich connection

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IMMICH_BASE_URL` | Yes | — | Immich server URL, e.g. `https://photos.example.com` |
| `IMMICH_API_KEY` | Yes | — | Immich API key |
| `IMMICH_TIMEOUT_SECONDS` | No | `30` | HTTP request timeout |
| `IMMICH_VERIFY_SSL` | No | `true` | Verify SSL certificates |

### Sync behaviour

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IMMICH_STORAGE_PREFIX` | No | `immich` | S3 path prefix for synced images |
| `IMMICH_SKIP_EXISTING` | No | `true` | Skip images already in the database |
| `IMMICH_MAX_IMAGES` | No | `20` | Maximum Immich-sourced images in the database (`0` = unlimited) |
| `IMMICH_RETENTION_DAYS` | No | `7` | Days before Immich images expire (`0` = never) |
| `IMMICH_TARGET_WIDTH` | No | — | Resize images to this width before storing |
| `IMMICH_TARGET_HEIGHT` | No | — | Resize images to this height before storing |

### S3 write access

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `S3_WRITER_ENDPOINT` | Yes | — | S3 endpoint, e.g. `garage.storage.svc:3900` |
| `S3_WRITER_ACCESS_KEY` | Yes | — | Write-access key |
| `S3_WRITER_SECRET_KEY` | Yes | — | Write-access secret |
| `S3_WRITER_BUCKET` | No | `inky-images` | Target bucket |
| `S3_WRITER_SECURE` | No | `false` | Use HTTPS |
| `S3_WRITER_REGION` | No | — | S3 region (omit for MinIO/Garage) |

### Gemini batch generation

Required only when running the `gemini` subcommand.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google Generative AI key. The model id is read from each preset's `model_name` column (default `gemini-2.5-flash-image`) — change it via the UI or `PUT /api/genai/presets/{id}`. |
| `GEMINI_SYNC_STORAGE_PREFIX` | No | `gemini` | S3 path prefix for generated images |

## Sync job configuration

Sync jobs are stored in the `immich_sync_jobs` table and managed via the API (`/api/sync-jobs`).

**Core fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | — | Unique job name |
| `is_active` | bool | `true` | Enable/disable this job |
| `target_device_id` | UUID | — | Device ID (determines image dimensions) |
| `strategy` | enum | `RANDOM` | `RANDOM` or `SMART` (CLIP semantic search) |
| `query` | str | — | Search query (required for `SMART` strategy) |
| `count` | int | `10` | Images to sync per run |
| `random_pick` | bool | `false` | Random sample from smart search results |
| `overfetch_multiplier` | int | `3` | Fetch multiplier for client-side filtering |
| `min_color_score` | float | `0.5` | Minimum Spectra 6 color compatibility (0.0–1.0) |
| `min_vibrancy_score` | float | `0.2` | Minimum vibrancy score (0.0–1.0) |

**Immich API filters:**

| Field | Type | Description |
|-------|------|-------------|
| `album_ids` | list[str] | Album UUIDs |
| `person_ids` | list[str] | Person UUIDs |
| `tag_ids` | list[str] | Tag UUIDs |
| `is_favorite` | bool | Favorites only |
| `city`, `state`, `country` | str | Location filters |
| `taken_after`, `taken_before` | datetime | Date range |
| `rating` | int | Minimum Immich rating (0–5) |

### Color and vibrancy scores

`min_color_score` measures how well an image's colors match the Inky Impression Spectra 6 palette (black, white, red, yellow, green, blue). Higher scores mean less dithering. Set to `0.0` to disable.

`min_vibrancy_score` measures image saturation and contrast. Low-vibrancy images (near-grayscale or very flat) often look poor on e-ink. Set to `0.0` to disable.

### Example: creating a sync job via the API

```bash
curl -X POST http://api.local:8000/api/sync-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "family-favorites",
    "target_device_id": "550e8400-e29b-41d4-a716-446655440000",
    "strategy": "RANDOM",
    "count": 20,
    "is_favorite": true
  }'
```

## AI generation (`/api/genai/*`)

The Gemini integration is configured through three DB-backed resources, all
managed through the API and the UI's GenAI page. Defaults are seeded on
first run by the `0004_add_ai_prompts_and_gemini_jobs` migration.

### Prompt blocks (`prompt_blocks`)

A prompt block is one reusable text fragment scoped to a single concern.

| Field | Type | Description |
|-------|------|-------------|
| `kind` | enum | One of `style`, `palette`, `legibility`, `composition`, `background` |
| `name` | str | Unique within a kind |
| `text` | str | Prompt fragment. Composition blocks may include a `{subject}` placeholder. |
| `is_default` | bool | At most one default per kind, used as the fallback when a preset isn't fully specified |

REST: `GET/POST /api/genai/blocks`, `GET/PUT/DELETE /api/genai/blocks/{id}`.

### Prompt presets (`prompt_presets`)

A preset is a named bundle of one block per kind plus the Gemini model
they should be sent to. Both batch jobs and on-demand generation reference
a preset.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Unique preset name |
| `style_block_id`, `palette_block_id`, `legibility_block_id`, `composition_block_id`, `background_block_id` | UUID | One block per kind |
| `model_name` | str | Gemini image model id (default `gemini-2.5-flash-image`) — changing this re-targets every job/request that uses the preset |
| `is_default` | bool | The preset used when the generate request omits `preset_id` |

REST: `GET/POST /api/genai/presets`, `GET/PUT/DELETE /api/genai/presets/{id}`.

### Gemini sync jobs (`gemini_sync_jobs`)

A batch generation job — analogous to `ImmichSyncJob` but for AI output.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Unique job name |
| `is_active` | bool | Enable/disable |
| `target_device_id` | UUID | Target device — provides display dimensions |
| `prompt_preset_id` | UUID | Preset used to render the prompt and pick the model |
| `is_portrait` | bool | `true` → 3:4 aspect ratio, `false` → 4:3 |
| `subjects` | list[str] | One Gemini call per subject, repeated `images_per_subject` times per run |
| `images_per_subject` | int (1-10) | Variations per subject |
| `retention_days` | int? | Optional expiry; the API cleans up matching images after this many days |

REST: `GET/POST /api/genai/jobs`, `GET/PUT/DELETE /api/genai/jobs/{id}`.

### On-demand generation

`POST /api/genai/generate` accepts:

```json
{
  "subject": "Ada Lovelace",
  "target_device_id": "550e8400-e29b-41d4-a716-446655440000",
  "preset_id": null,
  "is_portrait": true,
  "push_immediately": true
}
```

Returns `202 Accepted` with a `task_id`. The API runs Gemini in a background
task, registers the result with `source_name="gemini"`, and (when
`push_immediately` is true and the target device is online) issues an MQTT
display command immediately. Returns `503` if `API_GEMINI_API_KEY` is not
configured.
