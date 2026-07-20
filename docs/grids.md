# Grids

A **grid** is a virtual canvas in physical centimetres on which one or more
Inky displays are arranged so they jointly show slices of a single source
image. The API pre-renders each device's slice at its native pixel resolution
and pushes it through the existing MQTT `DisplayCommand` flow — controllers
need no grid-specific code.

Grids are also the universal target for **display jobs** (see
[motd.md](motd.md)) and **image groups**: every kind of content flows
through one **content queue** per grid. The queue interleaves groups
(worker-generated screens or operator-curated sets) with loose pool
images; fresh (never-shown) entries play first in the operator's order,
then the least recently shown entry replays. Each grid additionally
carries a daily display schedule (`display_*` columns: enabled, "HH:MM"
local time, weekday mask, IANA timezone, duration) that front-runs the
queue with the newest generated group and holds it. A single display
participates in that system by living in a one-panel grid.

## Mental model

```
            grid.width_cm  (computed)
   ┌──────────────────────────────────┐
   │ ┌─────────┐┌─────────┐┌────────┐ │
   │ │ row 0   ││ row 0   ││ row 0  │ │  grid.height_cm
   │ │ col 0   ││ col 1   ││ col 2  │ │  (computed)
   │ └─────────┘└─────────┘└────────┘ │
   │      ┌─────────┐┌─────────┐      │
   │      │ row 1   ││ row 1   │      │
   │      │ col 0   ││ col 1   │      │
   │      └─────────┘└─────────┘      │
   └──────────────────────────────────┘
```

- A grid is defined as a **tile layout**: rows of devices, top-down and
  left-to-right, assumed to sit flush against each other (no white space).
- Every cm value is **computed** from the device profiles' physical
  dimensions: canvas width = widest row, canvas height = sum of row heights.
  Mixed sizes are centred — a shorter panel is centred vertically within its
  row, a narrower row centred horizontally on the canvas.
- Each placement carries its **slot address** (`row`, `col`) — the stable,
  user-facing handle a display job uses to map content onto panels — plus
  the computed cm-rectangle used by the crop math.
- The source image is **cover-fitted** to the canvas (preserves aspect;
  centre-crops overflow on one axis), and each device's cm-rectangle
  projects onto the source pixels. The API uploads the resulting JPEG to S3
  and pushes a normal display command to the controller.

## Decisions

These are the choices made during design — read here before changing the
contract.

### Layout in, centimetres stored

Users arrange tiles; the server computes and persists cm-rectangles.

- Real-world wall arrangement is measured in cm and the crop math needs cm,
  but nobody should have to type coordinates: panel dimensions are known
  per profile, so a flush tile arrangement determines every position.
- The cm model is kept underneath (rather than replaced by a pure cell
  grid) so gapped or bezel-compensated layouts remain possible later
  without a schema change.
- The rect is snapshotted at layout time: a later profile-dimension
  correction does not silently shift existing placements.

### Physical dimensions live on `DeviceProfile`

`physical_width_cm` / `physical_height_cm` are stored once per panel model
(Pimoroni's published active-area specs). Devices and grid placements both
derive their physical size from the profile. Per-mounting overrides aren't
supported; if your bezel/frame changes effective area, correct the profile
(or extend the model).

### One grid per device

A device belongs to at most one grid's layout — enforced when a layout is
applied. This keeps slot addressing unambiguous and lets jobs treat "the
panel at row 1, col 0" as a stable target.

### API-side cropping, push pre-rendered slices

The display path uploads `grids/{grid_id}/{image_id}/{device_id}.jpg` and
sends each controller a normal `DisplayCommand` pointing at its slice.
Alternatives considered:

- Cropping in the controller via a new "crop box" command field — requires
  every controller to download the full (potentially multi-megapixel) source,
  duplicates work N times, needs a controller release.
- Stitching at display time on the device side — same downsides plus
  controller complexity.

The chosen path keeps controllers dumb, makes failures observable (each
slice is an inspectable JPEG in S3), and storage cost is trivial for e-ink
resolutions.

### Cover (crop-to-fill) is the only fit mode

Matches existing per-device behaviour, produces edge-to-edge results without
configuration, and avoids the "what background colour fills the letterbox?"
question. `fit_mode = contain|cover` can be added later if it becomes
desirable.

### Grid-mode arbitration: one claim per device at a time

The mechanism is the `devices.claimed_by_grid_id` column:

- `NULL` = the device runs its own solo rotation.
- Non-NULL = the named grid currently owns it (via its content queue);
  solo rotation skips this device until the claim is released.

Claims end by removing the device from the layout, or via
`POST /api/grids/{id}/release` when the grid's queue is empty (with queue
content, release instead resumes the queue immediately — see below). A
manual image push while a group is showing is an operator override: the
held group is dropped and the queue resumes from there.

### Explicit image-to-grid assignment

An `Image` row has an optional `target_grid_id`. Solo per-device rotation
excludes images with that field set; the grid rotation pool is exactly the
set of images carrying its id. Images with a `group_id` leave both solo
and pool rotation — their group plays as one queue entry instead.

A many-to-many table (images ↔ grids) was considered and rejected on the
grounds that grids tend to be long-lived and image curation is per-grid in
practice. Upgrading to M2M later is straightforward.

## API surface

All under `/api/grids`.

| Endpoint                            | Purpose                                              |
| ----------------------------------- | ---------------------------------------------------- |
| `GET /`                             | List grids (`?include_devices=true` to embed)        |
| `POST /`                            | Create grid from a tile layout (`name`, `rows`)      |
| `GET /{id}`                         | Detail, includes placements with slot addresses      |
| `PUT /{id}`                         | Rename, change cadence, or replace the layout        |
| `DELETE /{id}`                      | Delete; releases claims; clears `target_grid_id`     |
| `POST /{id}/display` (`{image_id}`) | Render slices + push to every member device          |
| `POST /{id}/display-group` (`{group_id}`) | Show a group now, held per the grid's duration |
| `POST /{id}/next`                   | Advance the queue one step now                       |
| `POST /{id}/release`                | End a held group; resume the queue immediately (jittered next refresh); with an empty queue, release devices to solo |
| `GET /{id}/queue`                   | The queue in predicted playback order                |
| `PUT /{id}/queue`                   | Persist the operator's queue order (groups + images share one sequence) |
| `GET /{id}/display-status`          | Current group/frame/hold + per-panel content         |

`rows` is a list of lists of device UUIDs — the visual arrangement. The
response embeds each placement's `row`/`col` slot plus its computed
bottom-left (Y-up) cm coordinates for the canvas preview.

The image router also has a `target_grid_id` filter on `GET /api/images`
and accepts the field on upload (`POST /api/images`) and update.

## Display flow

```
operator                                  API                              MQTT broker            controller(s)
   │                                       │                                    │                       │
   │ POST /api/grids/{id}/display          │                                    │                       │
   │──────────────────────────────────────▶│                                    │                       │
   │                                       │ load placements                    │                       │
   │                                       │ fetch source image from S3         │                       │
   │                                       │ for each device:                   │                       │
   │                                       │   compute crop box in cm           │                       │
   │                                       │   crop + resize to device px       │                       │
   │                                       │   upload grids/<id>/<img>/<dev>.jpg│                       │
   │                                       │   set claimed_by_grid_id           │                       │
   │                                       │   publish DisplayCommand ───────────▶                       │
   │                                       │                                    │ ───────────────────▶ controller A
   │                                       │                                    │ ───────────────────▶ controller B
   │ 200 OK                                │                                    │                       │
   │◀──────────────────────────────────────│                                    │                       │
   │                                       │              acks                  │ ◀─────────────────────│
   │                                       │◀───────────────────────────────────│                       │
```

## Worked example

A 2-display wall of 13.3" panels side by side:

```bash
# 1. Create the grid from the layout — one row, two panels. The canvas
#    (54.2 x 20.3 cm) and both placements are computed from the profiles.
curl -X POST localhost:8000/api/grids \
  -H "content-type: application/json" \
  -d '{"name": "living-wall", "rows": [["<device_a_uuid>", "<device_b_uuid>"]]}'
# → {"id": "<grid_id>", "width_cm": 54.2, "height_cm": 20.3, "devices": [...]}

# 2. Upload an image targeted at the grid (UI: pick target grid in the upload form).
#    Or update an existing image:
curl -X PUT localhost:8000/api/images/<image_id> \
  -H "content-type: application/json" \
  -d '{"target_grid_id": "<grid_id>"}'

# 3. Display.
curl -X POST localhost:8000/api/grids/<grid_id>/display \
  -H "content-type: application/json" \
  -d '{"image_id": "<image_id>"}'

# 4. Later, hand the devices back to solo rotation:
curl -X POST localhost:8000/api/grids/<grid_id>/release
```

## Operational notes

- **The grid's `scheduled_next_at` drives the rotation loop.** It's bumped
  whenever new content is pushed; the rotation tick (every 30 s) advances
  the grid's queue when due. A group occupies one refresh per frame:
  slot-addressed images show simultaneously (multi-image slots rotate),
  full-canvas images show one per refresh. On release the panels update
  immediately and the *next* refresh is randomly jittered so several grids
  released together don't flash in lockstep every interval afterwards.
- **Member devices stay claimed across image transitions.** A grid pulling
  its next image does *not* release devices between images. Use
  `POST /release` (or edit the layout / delete the grid) to return them to
  solo rotation.
- **Controllers are unchanged.** No grid-specific code lives on the device
  side; a controller just receives a normal display command with a path
  pointing into the `grids/` prefix.

## Out of scope (today)

- Fit modes other than cover.
- Gaps / bezel-mullion compensation between adjacent panels — the layout
  assumes panels sit flush. (The stored cm model already supports gaps;
  only the layout computation would need a spacing input.)
- Many-to-many image-to-grid pools.
- Per-mounting physical-size overrides.
- Auto-detect "this image fits grid X" — image assignment is explicit.
