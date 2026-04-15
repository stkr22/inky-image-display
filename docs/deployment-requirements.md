# Deployment Requirements

## External dependencies

- **PostgreSQL** — shared database for all services
- **S3-compatible storage** (MinIO, Garage, AWS S3) — image file storage
- **Immich** — photo library source (required only for the sync service)

## Environment variables

See [configuration.md](configuration.md) for the complete reference. A minimal set for each service:

### API

```env
API_DATABASE_URL=postgresql+asyncpg://inky:secret@db.svc:5432/inky
API_S3_ENDPOINT=garage.storage.svc:3900
API_S3_WRITER_ACCESS_KEY=<write-key>
API_S3_WRITER_SECRET_KEY=<write-secret>
API_S3_READER_ACCESS_KEY=<read-key>
API_S3_READER_SECRET_KEY=<read-secret>
```

### Controller

```env
DEVICE__ID=inky-kitchen
DEVICE__ROOM=Kitchen
API__URL=ws://api.svc:8000
```

S3 credentials are delivered automatically at registration — the controller does not need them in advance.

### Sync

```env
POSTGRES_PASSWORD=secret
IMMICH_BASE_URL=https://photos.example.com
IMMICH_API_KEY=<api-key>
S3_WRITER_ENDPOINT=garage.storage.svc:3900
S3_WRITER_ACCESS_KEY=<write-key>
S3_WRITER_SECRET_KEY=<write-secret>
```

## Database tables

Tables are created automatically on startup (API and Sync both call `CREATE TABLE IF NOT EXISTS`):

| Table | Created by | Description |
|-------|-----------|-------------|
| `devices` | API | Registered controller devices |
| `images` | API / Sync | Image metadata and S3 paths |
| `immich_sync_jobs` | API / Sync | Sync job configuration |

## S3 bucket layout

Both the API and Sync write to the same bucket (`inky-images` by default).

| Prefix | Written by | Description |
|--------|-----------|-------------|
| `<source_name>/<uuid>.jpg` | API (upload) | Manually uploaded images |
| `immich/<uuid>.jpg` | Sync | Images synced from Immich |

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

### Sync (CronJob)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: inky-immich-sync
spec:
  schedule: "0 * * * *"   # hourly
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: sync
              image: ghcr.io/stkr22/inky-image-display-sync:latest
              command: ["immich-sync"]
              envFrom:
                - secretRef:
                    name: inky-sync-secrets
              env:
                - name: POSTGRES_HOST
                  value: db.svc
                - name: POSTGRES_DB
                  value: inky
                - name: IMMICH_BASE_URL
                  value: https://photos.example.com
                - name: S3_WRITER_ENDPOINT
                  value: garage.storage.svc:3900
                - name: S3_WRITER_BUCKET
                  value: inky-images
```
