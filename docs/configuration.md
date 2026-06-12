# Configuration

All configuration is via environment variables. The controller additionally supports a YAML file for structured settings.

## API (`inky-image-display-api`)

All variables are prefixed with `API_`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_DATABASE_PATH` | Yes | — | Path to the SQLite database file, e.g. `/data/inky.db` |
| `API_S3_ENDPOINT` | Yes | — | S3 endpoint, e.g. `s3.example.com`. This value is handed to controllers at registration and they pull images from it directly, so it must be reachable from **outside** the cluster (public/ingress address), not a cluster-internal service name. |
| `API_S3_WRITER_ACCESS_KEY` | Yes | — | Write-access S3 key (for image upload) |
| `API_S3_WRITER_SECRET_KEY` | Yes | — | Write-access S3 secret |
| `API_S3_READER_ACCESS_KEY` | Yes | — | Read-only S3 key (sent to controllers on registration) |
| `API_S3_READER_SECRET_KEY` | Yes | — | Read-only S3 secret |
| `API_S3_BUCKET` | No | `inky-images` | S3 bucket name |
| `API_S3_SECURE` | No | `false` | Use HTTPS for S3 |
| `API_S3_REGION` | No | — | S3 region (omit for MinIO/Garage) |
| `API_DEFAULT_DISPLAY_DURATION` | No | `3600` | Default image display duration (seconds) |
| `API_MQTT_HOST` | Yes | — | MQTT broker hostname **used by the API itself** (typically an internal/cluster address) |
| `API_MQTT_PORT` | No | `1883` | MQTT broker port |
| `API_MQTT_USERNAME` | No | — | MQTT username |
| `API_MQTT_PASSWORD` | No | — | MQTT password |
| `API_MQTT_TLS` | No | `false` | Use TLS for the broker connection |
| `API_MQTT_TRANSPORT` | No | `tcp` | `tcp` or `websockets` (use ws to tunnel via HTTP(S) ingress) |
| `API_MQTT_WEBSOCKET_PATH` | No | `/mqtt` | HTTP path the broker serves WS on (when `transport=websockets`) |
| `API_MQTT_CLIENT_ID` | No | `inky-api` | MQTT client identifier |
| `API_MQTT_KEEP_ALIVE` | No | `30` | MQTT keep-alive interval (seconds) |
| `API_DEVICE_MQTT_HOST` | Yes | — | MQTT broker hostname **handed to controllers** in the registration response (typically the public/ingress address) |
| `API_DEVICE_MQTT_PORT` | No | `1883` | Port advertised to controllers |
| `API_DEVICE_MQTT_USERNAME` | No | — | MQTT username for controllers (use a separate, ACL-restricted account) |
| `API_DEVICE_MQTT_PASSWORD` | No | — | MQTT password for controllers |
| `API_DEVICE_MQTT_TLS` | No | `false` | Whether controllers should connect with TLS |
| `API_DEVICE_MQTT_TRANSPORT` | No | `tcp` | `tcp` or `websockets` for the controller connection |
| `API_DEVICE_MQTT_WEBSOCKET_PATH` | No | `/mqtt` | HTTP path controllers use for MQTT-over-WebSockets |
| `API_DEVICE_MQTT_KEEP_ALIVE` | No | `30` | MQTT keep-alive interval advertised to controllers |
| `API_GEMINI_API_KEY` | No | — | Google Generative AI key. Required only for `POST /api/genai/generate`; leave unset to disable on-demand generation (returns 503). |
| `API_IMMICH_BASE_URL` | No | — | Immich base URL for the read-only browse proxy (`GET /api/immich/albums`, `/people`, `/tags`) that powers name-based sync-job filter pickers in the UI. Leave unset to disable (returns 503; the UI falls back to raw-ID inputs). |
| `API_IMMICH_API_KEY` | No | — | Immich API key for the browse proxy. Use the same values the sync service is configured with. |
| `API_IMMICH_TIMEOUT_SECONDS` | No | `20.0` | Timeout for Immich browse-proxy requests (seconds). |
| `API_MEDIA_CACHE_MAX_AGE` | No | `86400` | `Cache-Control: max-age` for `/media` responses (originals and thumbnails). |
| `API_WEB_DIST_PATH` | No | — | Directory containing the built React frontend (`packages/web/dist`). When set, the API serves it with an SPA fallback; when unset the API is headless. |

### MQTT transport / TLS combinations

`tls` and `transport` are independent. The four combinations map to:

| `tls` | `transport` | Effective URL | Typical port | Use when |
|-------|-------------|---------------|--------------|----------|
| `false` | `tcp` | `mqtt://`  | `1883` | LAN broker, no TLS (dev / trusted network) |
| `true`  | `tcp` | `mqtts://` | `8883` | Dedicated MQTT VIP with its own cert |
| `false` | `websockets` | `ws://`  | `8080`/`9001` | Behind a plaintext reverse proxy (rare) |
| `true`  | `websockets` | `wss://` | `443` | Broker behind your existing HTTPS Ingress (recommended for K8s) |

The `API_MQTT_*` block above governs the API's own broker connection.
A parallel `API_DEVICE_MQTT_*` block (same fields, same semantics) is
what the API hands to controllers in the registration response, so the
two roles can use different endpoints and credentials — e.g. the API
talks to the broker over plaintext TCP on an internal address while
controllers connect via WSS through the public HTTPS ingress.

## Web frontend (`packages/web`)

The React frontend is built as static files (`npm run build`) and served by the
API itself when `API_WEB_DIST_PATH` points at the build output (the API
container image does this by default). The API also owns the browser-facing
`/media/{object_key}` proxy, which streams images from S3 and generates cached
thumbnails on demand (`?w=240|480|960`), so the browser never needs S3
credentials or direct bucket access.

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
| `CONTROLLER_DISPLAY__MOCK_PROFILE_KEY` | `inky_impression_13_spectra6` | Seeded device-profile key whose panel dimensions the mock display should report. Valid keys: `inky_impression_4_spectra6`, `inky_impression_7_spectra6`, `inky_impression_13_spectra6`. |
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
| `target_device_profile_id` | UUID | — | Device profile (panel) this job syncs for — determines target dimensions. See `GET /api/device-profiles`. |
| `orientation` | str \| null | `null` | Optional orientation override (`landscape` / `portrait`). `null` means "any" — images are sized for the profile's landscape-native dims. |
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
| `album_ids` | list[str] | Album UUIDs — intersection (asset must be in **all** listed albums) |
| `person_ids` | list[str] | Person UUIDs — intersection (asset must show **all** listed people) |
| `tag_ids` | list[str] | Tag UUIDs — union (asset matches if it has **any** listed tag) |
| `is_favorite` | bool | Favorites only |
| `city`, `state`, `country` | str | Location filters |
| `taken_after`, `taken_before` | datetime | Date range |
| `rating` | int | Minimum Immich rating (0–5) |

> **Multi-tag semantics:** Immich's search endpoints intersect multiple `tagIds`
> (an asset would need *every* tag at once). To match the intuitive "photos from
> any of these tags", the `RANDOM` strategy issues one query per tag and unions
> the results (then shuffles). `album_ids` and `person_ids` keep Immich's native
> intersection behavior. The `RANDOM` strategy uses Immich's `/search/random`
> endpoint, which orders the whole filtered set randomly — so picks vary across
> the entire album, not just recent photos. `overfetch_multiplier × count` sizes
> each query (capped at Immich's maximum of 1000) so client-side orientation/size
> filters still leave enough candidates.

### Color and vibrancy scores

`min_color_score` measures how well an image's colors match the Inky Impression Spectra 6 palette (black, white, red, yellow, green, blue). Higher scores mean less dithering. Set to `0.0` to disable.

`min_vibrancy_score` measures image saturation and contrast. Low-vibrancy images (near-grayscale or very flat) often look poor on e-ink. Set to `0.0` to disable.

### Example: creating a sync job via the API

```bash
curl -X POST http://api.local:8000/api/sync-jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "family-favorites",
    "target_device_profile_id": "4a688010-6c69-5297-b574-67e5c75ea29f",
    "orientation": "landscape",
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
| `target_device_profile_id` | UUID | Target device profile — provides panel dimensions |
| `prompt_preset_id` | UUID | Preset used to render the prompt and pick the model |
| `orientation` | str | `portrait` → 3:4 aspect ratio, `landscape` → 4:3. Determines image dims and which devices receive the result. |
| `subjects` | list[str] | One Gemini call per subject, repeated `images_per_subject` times per run |
| `images_per_subject` | int (1-10) | Variations per subject |
| `retention_days` | int? | Optional expiry; the API cleans up matching images after this many days |

REST: `GET/POST /api/genai/jobs`, `GET/PUT/DELETE /api/genai/jobs/{id}`.

### On-demand generation

`POST /api/genai/generate` accepts:

```json
{
  "subject": "Ada Lovelace",
  "target_device_profile_id": null,
  "preset_id": null,
  "orientation": "portrait",
  "push_immediately": true
}
```

`target_device_profile_id` is optional — when omitted the API uses the
profile marked `is_default` in `device_profiles`.

Returns `202 Accepted` with a `task_id`. The API runs Gemini in a background
task, registers the result with `source_name="gemini"`, and (when
`push_immediately` is true) dispatches a display command to a *random* online
device whose `device_profile_id` and `display_orientation` both match the
request. If no matching device is online the image is still persisted — it'll
surface in the next rotation when a matching device reconnects. Returns `503`
if `API_GEMINI_API_KEY` is not configured.

### Device profiles (`/api/device-profiles`)

The supported Inky lineup is seeded by migration 0007 with stable UUIDs
(via `uuid5`) so the same IDs are used in every environment. The lineup
is not user-extensible.

| Field | Type | Description |
|-------|------|-------------|
| `key` | str | Stable slug (e.g. `inky_impression_13_spectra6`) — used by the controller at registration |
| `name` | str | Human label, editable via `PATCH /api/device-profiles/{id}` |
| `width`, `height` | int | Panel-native dimensions (landscape, longer side first); immutable |
| `model` | str | Hardware identifier; immutable |
| `is_default` | bool | Exactly one row marked default — used by genai when no profile is supplied. Flip via `POST /api/device-profiles/{id}/set-default`. |
