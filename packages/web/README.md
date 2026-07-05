# inky-image-display-web

React operator UI (port of the former NiceGUI UI), keeping the same bento /
Apple-minimal design system. Vite + React + TypeScript + React Router +
TanStack Query — no component library; the design system CSS is hand-ported
into `src/styles/global.css`.

## Architecture

The browser app talks **same-origin** only, and the API service owns all of it:

- `/api/*` → REST endpoints (`packages/api`)
- `/media/*` → the API's S3 streaming proxy. Append `?w=240|480|960` for a
  lazily generated, bucket-cached thumbnail; omit for the original.
- everything else → this app's static build, served by the API when
  `API_WEB_DIST_PATH` points at `dist/` (the API container does this by default).

In development both paths are proxied by the Vite dev server
(`vite.config.ts`) to the API on `localhost:8000`; override with
`WEB_API_PROXY` (and `WEB_MEDIA_PROXY` if media is hosted elsewhere).

## Commands

```bash
npm install        # install dependencies
npm run dev        # dev server on :5173 with API/media proxies
npm run typecheck  # tsc only
npm run build      # typecheck + production bundle into dist/
npm run test:e2e   # Playwright suite (see below)
```

## End-to-end tests

`e2e/` holds a Playwright suite that runs against an **already-running stack**
(API serving the built frontend, with its S3/MQTT dependencies up — the
devcontainer provides these as sibling services):

```bash
npm run build
API_DEVICE_MQTT_HOST=mosquitto API_WEB_DIST_PATH=$PWD/dist uv run inky-image-display-api &
npx playwright install chromium   # first run only
npm run test:e2e                  # or WEB_E2E_BASE_URL=... to target elsewhere
```

- `smoke.spec.ts` — every route renders its heading with zero console errors,
  failed requests, or unexpected 4xx/5xx (503s from the optional Immich/Gemini
  integrations are allowed); legacy redirects, jobs tab URL state, dark-mode
  persistence.
- `upload-crop.spec.ts` — full crop→upload flow with a canvas-generated image:
  verifies the panel preset yields exact pixel dimensions via the API, the
  thumbnail endpoint serves a variant, then deletes the image so reruns stay
  clean. Also seeds and searches an image through the gallery search box.
- `guest.spec.ts` — mints a guest invite on the Settings page, opens it in a
  fresh browser context, and verifies the restricted guest UI plus sign-out;
  also checks that a bogus invite token is rejected.

The tests are data-independent: they pass against an empty or populated
library and clean up everything they create.

## Layout

```
src/
├── lib/          api client, API types, date/interval formatting, image-fit math
├── components/   design-system primitives: layout/nav, tiles, dialogs, toasts, form fields
└── pages/        one file per route (Landing, Images, ImageDetail, ImageUpload,
                  Displays, GridDetail, Jobs, SyncJobForm, GeminiJobForm, GenAI, Settings)
```

Routing matches the NiceGUI app one-to-one, including the legacy redirects
(`/sync-jobs` → `/jobs`, `/gemini-jobs` → `/jobs?tab=gemini`, `/generate` and
`/prompts` → `/genai`), so existing deep links keep working.

## Deliberate differences from the NiceGUI app

- **Parallel dashboard loading** — landing tiles each fetch independently via
  TanStack Query instead of rendering sequentially server-side.
- **Cached navigation** — list data is cached (10 s staleness) and refetched in
  the background, so switching sections is instant.
- **Upload UX** — drag-and-drop zone with client-side preview, dimensions read
  in the browser, title prefilled from the filename, and the portrait switch
  auto-set from the decoded image.
- **Optimistic job toggles** — the active switch flips immediately and rolls
  back on error.
- **Gemini job delete asks for confirmation** (the NiceGUI version deleted
  without confirming — almost certainly an oversight).
- **Schedule rows for grids deep-link to the grid detail page** instead of the
  generic list.

## Features beyond the NiceGUI app

- **Recent generations** on the GenAI page (polls `GET /api/genai/tasks`;
  shows queued/running/completed/failed with links to the produced image).
- **Gallery search** (debounced, backed by the `search` query param) and a
  **multi-select mode** with bulk delete / bulk grid assignment.
- **Name-based Immich filter pickers** in the sync-job form, backed by the
  API's `/api/immich/*` browse proxy; falls back to raw-ID chips when the
  proxy is not configured.
- **Offline since** timestamp on device cards (from `last_seen`).
- **Dark mode** — toggle in the nav, persisted, defaults to the OS preference.
- **Crop at upload** — client-side crop dialog (react-easy-crop) with aspect
  presets from the target grid and device profiles; panel presets output the
  panel's exact pixel dimensions so the upload is directly sendable. Re-crops
  always start from the original file; the server only ever receives the
  cropped JPEG.
