# UI (`inky-image-display-ui`)

NiceGUI-based web UI served by a FastAPI app. Lets an operator browse and upload images, command displays, manage sync jobs (Immich + Gemini), and trigger on-demand AI image generation from a phone or laptop.

## Sections

The top nav has four sections:

| Path | Purpose |
|------|---------|
| `/images` | Library: browse, upload, edit, delete |
| `/devices` | Online wall + per-device controls (push next, pick image, clear) |
| `/jobs` | Tabbed list of Immich and Gemini sync jobs. The "New job" button follows the active tab and routes to `/sync-jobs/new` or `/gemini-jobs/new`; the per-source forms still live there for editing existing jobs |
| `/genai` | On-demand generation form on top, prompt library tucked behind an "Advanced" expansion below |

The GenAI page is the full AI surface: a Subject textarea (capped at 200 characters) plus target device-profile, preset, orientation, and "push immediately" toggles for one-off generation. The profile dropdown defaults to the row marked `is_default` in `device_profiles`; the resulting image lands on a random online device whose profile + orientation match (no device picker — that decision happens server-side at dispatch time). The collapsed Advanced section lets operators add or edit prompt blocks (style / palette / legibility / composition / background) and prompt presets — including the Gemini model name each preset binds to.

## Architecture

```
Browser ──HTTP──► UI container ──HTTP──► API container
                       │
                       └──S3──► MinIO / Garage (reader credentials)
```

The UI container hosts three pieces of surface area on one uvicorn process:

| Route | Purpose |
|-------|---------|
| `/` | NiceGUI UI (mounted ASGI app) |
| `/health` | Liveness probe |
| `/media/{object_key:path}` | Streams image bytes from S3 using reader credentials |
| `/internal/upload` | Accepts multipart uploads and forwards to the API |

Plain routes are registered before the NiceGUI mount so FastAPI matches them first.

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
