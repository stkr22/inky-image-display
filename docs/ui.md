# UI (`inky-image-display-ui`)

Flet-based web UI served by a FastAPI app. Lets an operator browse and upload images, command displays, and manage Immich sync jobs from a phone or laptop.

## Architecture

```
Browser ──HTTP──► UI container ──HTTP──► API container
                       │
                       └──S3──► MinIO / Garage (reader credentials)
```

The UI container hosts three pieces of surface area on one uvicorn process:

| Route | Purpose |
|-------|---------|
| `/` | Flet UI (mounted ASGI app) |
| `/health` | Liveness probe |
| `/media/{object_key:path}` | Streams image bytes from S3 using reader credentials |
| `/internal/upload` | Accepts multipart uploads from Flet's `FilePicker` and forwards to the API |

Plain routes are registered before the Flet mount so FastAPI matches them first.

Images are proxied through the UI rather than fetched directly by the browser — avoids configuring CORS on S3 and keeps reader credentials server-side.

## Security

**No authentication.** Assume trusted LAN only. Do not expose the UI to the public internet without fronting it with a reverse proxy that enforces auth.

## Local development

```bash
export UI_API_BASE_URL=http://localhost:8000
export UI_S3_ENDPOINT=localhost:9000
export UI_S3_READER_ACCESS_KEY=reader
export UI_S3_READER_SECRET_KEY=readerpass
uv run --package inky-image-display-ui inky-image-display-ui
```

Then open <http://localhost:8001/>.

See [configuration.md](configuration.md#ui-inky-image-display-ui) for the full environment variable reference.

## Container

```bash
docker buildx build -f packages/ui/Containerfile --load -t ui:dev .
docker run --rm -p 8001:8001 \
  -e UI_API_BASE_URL=http://api:8000 \
  -e UI_S3_ENDPOINT=minio:9000 \
  -e UI_S3_READER_ACCESS_KEY=reader \
  -e UI_S3_READER_SECRET_KEY=readerpass \
  ui:dev
```
