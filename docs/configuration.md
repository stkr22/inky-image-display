# Configuration

All configuration is via environment variables. The controller additionally supports a YAML file for structured settings.

## API (`inky-image-display-api`)

All variables are prefixed with `API_`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_DATABASE_URL` | Yes | — | SQLAlchemy async URL, e.g. `postgresql+asyncpg://user:pass@host/db` |
| `API_S3_ENDPOINT` | Yes | — | S3 endpoint, e.g. `garage.storage.svc:3900` |
| `API_S3_WRITER_ACCESS_KEY` | Yes | — | Write-access S3 key (for image upload) |
| `API_S3_WRITER_SECRET_KEY` | Yes | — | Write-access S3 secret |
| `API_S3_READER_ACCESS_KEY` | Yes | — | Read-only S3 key (sent to controllers on registration) |
| `API_S3_READER_SECRET_KEY` | Yes | — | Read-only S3 secret |
| `API_S3_BUCKET` | No | `inky-images` | S3 bucket name |
| `API_S3_SECURE` | No | `false` | Use HTTPS for S3 |
| `API_S3_REGION` | No | — | S3 region (omit for MinIO/Garage) |
| `API_DEFAULT_DISPLAY_DURATION` | No | `3600` | Default image display duration (seconds) |

## Controller (`inky-image-display-controller`)

The controller supports both a YAML file and environment variables. Environment variables take precedence; nested fields use `__` as a delimiter (e.g. `DEVICE__ID`).

### YAML configuration file

Pass the file path with `--config /path/to/config.yaml` or `-c`.

```yaml
device:
  id: inky-kitchen          # Unique device identifier
  room: Kitchen             # Optional room label

api:
  url: ws://api.local:8000  # API WebSocket base URL
  reconnect_interval: 5     # Initial reconnect delay (seconds)
  max_reconnect_interval: 60

s3:
  endpoint: garage.storage.svc:3900
  bucket: inky-images
  secure: false
  # access_key and secret_key are received from the API on registration
  # and do not need to be set here

display:
  orientation: landscape    # "landscape" or "portrait"
  saturation: 0.5           # Spectra 6 color saturation (0.0–1.0)
  mock: false               # true = no hardware required (for testing)
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVICE__ID` | `inky-display` | Device identifier |
| `DEVICE__ROOM` | — | Room label |
| `API__URL` | `ws://localhost:8000` | API WebSocket base URL |
| `API__RECONNECT_INTERVAL` | `5` | Initial reconnect delay (seconds) |
| `API__MAX_RECONNECT_INTERVAL` | `60` | Max reconnect delay (seconds) |
| `S3__ENDPOINT` | `localhost:9000` | S3 endpoint |
| `S3__BUCKET` | `inky-images` | S3 bucket |
| `S3__ACCESS_KEY` | — | S3 access key (normally provided by API at registration) |
| `S3__SECRET_KEY` | — | S3 secret key |
| `S3__SECURE` | `false` | Use HTTPS |
| `DISPLAY__ORIENTATION` | `landscape` | `landscape` or `portrait` |
| `DISPLAY__SATURATION` | `0.5` | Color saturation for Spectra 6 (0.0–1.0) |
| `DISPLAY__MOCK` | `false` | Use mock display (no hardware) |
| `DISPLAY__MOCK_WIDTH` | `1600` | Mock display width (pixels) |
| `DISPLAY__MOCK_HEIGHT` | `1200` | Mock display height (pixels) |
| `DEVICE_ID` | — | Overrides `DEVICE__ID` (also accepted as `--device-id` CLI flag) |

## Sync (`inky-image-display-sync`)

### Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_HOST` | No | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | No | `5432` | PostgreSQL port |
| `POSTGRES_DB` | No | `inky` | Database name |
| `POSTGRES_USER` | No | `inky` | Database user |
| `POSTGRES_PASSWORD` | Yes | — | Database password |

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
