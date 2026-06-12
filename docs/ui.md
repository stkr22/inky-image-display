# Web frontend (`packages/web`)

React single-page app (Vite + TypeScript + React Router + TanStack Query) with a
bento-style design system, served as static files by the API service. It
replaced the earlier NiceGUI UI service; the `/media` image proxy that service
hosted now lives in the API (`packages/api/.../routes/media.py`).

## Sections

The top nav has five sections:

| Path | Purpose |
|------|---------|
| `/images` | Library: browse, search, upload, edit, delete. Filter by source, orientation, or grid pool; multi-select mode for bulk delete / bulk grid assignment |
| `/displays` | Upcoming refresh schedule, online device wall with per-device controls (next, schedule, clear), and grid management |
| `/grids/{id}` | Grid detail: proportional canvas preview of how an image is cover-cropped onto each placed device, placement editing, per-grid image pool with resolution traffic-light badges |
| `/jobs` | Tabbed list of Immich and Gemini sync jobs (`?tab=gemini`). Create/edit forms live at `/sync-jobs/*` and `/gemini-jobs/*`. Immich filters use name-based pickers backed by the API's `/api/immich/*` browse proxy when configured |
| `/genai` | On-demand generation form, a "Recent generations" status list (backed by `GET /api/genai/tasks`), and the prompt block/preset library behind an Advanced expansion |
| `/settings` | Global default refresh interval |

Legacy deep links (`/generate`, `/prompts`, bare `/sync-jobs`, `/gemini-jobs`)
redirect to their new homes. A dark mode toggle in the nav persists per browser
and defaults to the OS preference.

## Architecture

```
Browser ──HTTP──► API container ──S3──► MinIO / Garage (writer credentials)
   ▲                  │
   └── static React   └── MQTT ──► devices
       bundle + /media proxy
```

- The browser talks **same-origin only**: `/api/*` for data, `/media/*` for
  images, everything else falls back to the SPA's `index.html`.
- `/media/{object_key}` streams originals with ETag/Cache-Control;
  `?w=240|480|960` serves a downscaled JPEG generated lazily on first request
  and cached in the bucket under `thumbs/w{width}/…`. Gallery and device-card
  views request `?w=480`; detail views load originals.
- No authentication — trusted LAN only (same model as before).

## Development

```bash
cd packages/web
npm install
npm run dev        # Vite dev server on :5173, proxying /api and /media to localhost:8000
npm run build      # typecheck + production bundle into dist/
```

Point a locally running API at the build output with
`API_WEB_DIST_PATH=$(pwd)/packages/web/dist`. The API container image builds
and bundles the frontend automatically.
