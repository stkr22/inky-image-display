# Deployment Requirements

## Helm chart

The recommended Kubernetes deployment is the Helm chart in
[`charts/inky-image-display`](../charts/inky-image-display/README.md),
published to `oci://ghcr.io/stkr22/charts/inky-image-display` on every
release and version-locked to the container images from the same tag. The
raw-manifest examples below remain as a reference for non-Helm setups.

## External dependencies

- **SQLite** — embedded database; file path set via `API_DATABASE_PATH`. Mount a persistent volume in containerised deployments. The sync service accesses the database only through the API — it does not need a direct database path.
- **S3-compatible storage** (MinIO, Garage, AWS S3) — image file storage
- **MQTT broker** (Mosquitto, EMQX, etc.) — used for command/ack/status traffic between the API and devices
- **Immich** — photo library source (required only for the Immich sync subcommand)
- **Google Generative AI key** — required only for `POST /api/genai/generate` (set as `API_GEMINI_API_KEY` on the API) and for `inky-image-display-sync gemini` (set as `GEMINI_API_KEY` on the sync container)

## Environment variables

See [configuration.md](configuration.md) for the complete reference. A minimal set for each service:

### API

```env
API_DATABASE_PATH=/data/inky.db
API_S3_ENDPOINT=garage.storage.svc:3900
API_S3_WRITER_ACCESS_KEY=<write-key>
API_S3_WRITER_SECRET_KEY=<write-secret>
API_S3_READER_ACCESS_KEY=<read-key>
API_S3_READER_SECRET_KEY=<read-secret>
API_MQTT_HOST=mqtt.svc
API_DEVICE_MQTT_HOST=mqtt.example.com
```

`API_MQTT_HOST` is the broker address used by the API process itself
(usually an internal cluster service). `API_DEVICE_MQTT_HOST` is the
address advertised to controllers in the registration response (usually
the public/ingress hostname). Both are required.

### Controller

```env
CONTROLLER_DEVICE__ID=inky-kitchen
CONTROLLER_DEVICE__ROOM=Kitchen
CONTROLLER_API__URL=http://api.svc:8000
CONTROLLER_MQTT__HOST=mqtt.svc
```

S3 credentials are delivered automatically at registration — the controller does not need them in advance.

### Sync

```env
DISPLAY_API_BASE_URL=http://api.svc:8000
IMMICH_BASE_URL=https://photos.example.com
IMMICH_API_KEY=<api-key>
S3_WRITER_ENDPOINT=garage.storage.svc:3900
S3_WRITER_ACCESS_KEY=<write-key>
S3_WRITER_SECRET_KEY=<write-secret>
# Required only for `inky-image-display-sync gemini`:
GEMINI_API_KEY=<gemini-key>
```

## Database tables

Tables are created automatically by the API on startup; AI tables are seeded with a default prompt library by the `0004` Alembic migration on first boot.

| Table | Created by | Description |
|-------|-----------|-------------|
| `devices` | API | Registered controller devices |
| `images` | API | Image metadata and S3 paths |
| `immich_sync_jobs` | API | Immich sync job configuration |
| `prompt_blocks` | API | Reusable AI prompt fragments per kind (style / palette / legibility / composition / background) |
| `prompt_presets` | API | Bundles of one block per kind plus the Gemini model id |
| `gemini_sync_jobs` | API | Gemini batch generation job configuration |

## S3 bucket layout

Both the API and Sync write to the same bucket (`inky-images` by default).

| Prefix | Written by | Description |
|--------|-----------|-------------|
| `<source_name>/<uuid>.jpg` | API (upload) | Manually uploaded images |
| `immich/<uuid>.jpg` | Sync (`immich`) | Images synced from Immich |
| `gemini/<uuid>.jpg` | API (`POST /api/genai/generate`) and Sync (`gemini`) | AI-generated images |

Two sets of credentials are recommended:
- **Writer** — used by the API (for uploads) and the Sync service
- **Reader** — distributed to controllers via the registration response; read-only access is sufficient

## Kubernetes deployment example

### API

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: inky-image-display-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: inky-image-display-api
  template:
    metadata:
      labels:
        app: inky-image-display-api
    spec:
      containers:
        - name: api
          image: ghcr.io/stkr22/inky-image-display-api:latest
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: inky-api-secrets
          env:
            - name: API_S3_ENDPOINT
              value: garage.storage.svc:3900
            - name: API_S3_BUCKET
              value: inky-images
```

### Sync worker (Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: inky-sync-worker
spec:
  replicas: 1   # claim cycles run one at a time
  template:
    spec:
      containers:
        - name: worker
          image: ghcr.io/stkr22/inky-image-display-sync:latest
          args: ["worker"]
          envFrom:
            - secretRef:
                name: inky-sync-secrets
          env:
            - name: DISPLAY_API_BASE_URL
              value: http://inky-image-display-api.svc:8000
            - name: WORKER_MQTT_HOST
              value: mosquitto.mqtt.svc.cluster.local
            - name: WORKER_ENABLE_IMMICH
              value: "true"
            - name: IMMICH_BASE_URL
              value: https://photos.example.com
            - name: S3_WRITER_ENDPOINT
              value: garage.storage.svc:3900
            - name: S3_WRITER_BUCKET
              value: inky-images
```

One long-running worker replaces the old per-family CronJobs. Per-job
cadence is a cron schedule set in the UI; the API wakes the worker over
MQTT when jobs are due (or when "Run now" is clicked), and the worker also
polls on `WORKER_POLL_INTERVAL_SECONDS` (default 600) as a safety net, so
a missed wake delays a run instead of losing it. Without `WORKER_MQTT_HOST`
the worker runs in poll-only mode.

Enable the other job families with `WORKER_ENABLE_GEMINI` /
`WORKER_ENABLE_DISPLAY` and add `GEMINI_API_KEY` to the secret; cadence is
likewise per job in the UI (Gemini jobs default to daily — generation is
billed per image).
