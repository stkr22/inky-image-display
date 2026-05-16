# Grids

A **grid** is a virtual canvas in physical centimetres on which two or more
Inky displays are arranged so they jointly show slices of a single source
image. The API pre-renders each device's slice at its native pixel resolution
and pushes it through the existing MQTT `DisplayCommand` flow — controllers
need no grid-specific code.

## Mental model

```
            grid.width_cm
   ┌────────────────────────────────────┐
   │                                    │
   │   ┌─────────┐         ┌─────────┐  │  grid.height_cm
   │   │ device  │         │ device  │  │
   │   │   A     │         │   B     │  │
   │   └─────────┘         └─────────┘  │
   │                                    │
   └────────────────────────────────────┘
```

- The grid has physical dimensions (`width_cm`, `height_cm`).
- Each placed device has its own rectangle on the canvas
  (`top_left_x_cm`, `top_left_y_cm`, `width_cm`, `height_cm`).
- The source image is **cover-fitted** to the canvas (preserves aspect; centre-
  crops overflow on one axis), and each device's cm-rectangle projects onto
  the source pixels. The API uploads the resulting JPEG to S3 and pushes a
  normal display command to the controller.

## Decisions

These are the choices made during design — read here before changing the
contract.

### Centimetres, not millimetres or pixels

- Real-world wall arrangement is measured in cm — sub-cm precision is not
  meaningful when mounting on plaster.
- Pixel coordinates would couple the canvas to a specific image and force
  every layout change to re-do crop math.
- An abstract cell grid (e.g. 3×2) was rejected because mixed panel sizes
  (4" + 13.3" on the same wall) don't tile uniformly.

### Physical dimensions live on `DeviceProfile`

`physical_width_cm` / `physical_height_cm` are stored once per panel model
(Pimoroni's published active-area specs). Devices and grid placements both
derive their physical size from the profile. Per-mounting overrides aren't
supported in v1; if your bezel/frame changes effective area, correct the
profile (or extend the model).

### Rectangle stored, midpoint accepted

The API accepts either a midpoint (`midpoint_x_cm`, `midpoint_y_cm`) or an
explicit top-left corner; it always persists the full rectangle
(`top_left_x_cm`, `top_left_y_cm`, `width_cm`, `height_cm`). Reasons:

- Crop math reads the rect directly — no recomputation per render.
- A later profile-dimension correction does not silently shift existing
  placements; the grid stays geometrically fixed.
- Midpoint input is the UX win — users only need to measure the centre of
  the panel against the wall.

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

### Cover (crop-to-fill) is the only fit mode in v1

Matches existing per-device behaviour, produces edge-to-edge results without
configuration, and avoids the "what background colour fills the letterbox?"
question. `fit_mode = contain|cover` can be added later if it becomes
desirable.

### Grid-mode arbitration: one claim per device at a time

A device can be a member of multiple grids but only **driven** by one at a
time. The mechanism is the `devices.claimed_by_grid_id` column:

- `NULL` = the device runs its own solo rotation.
- Non-NULL = the named grid currently owns it; solo rotation skips this
  device until the claim is released.

`POST /api/grids/{id}/display` (and the grid rotation tick) refuses with
`409` if any member device is already claimed by a different grid. No
timeout-based reclaim — claims end explicitly via `POST /api/grids/{id}/release`
or when the grid moves on to its next image.

This dodges the harder coordination problem of "device A in two grids,
both pick a different image" and matches how the rest of the system makes
state changes explicit.

### Explicit image-to-grid assignment

An `Image` row has an optional `target_grid_id`. Solo per-device rotation
excludes images with that field set; the grid rotation pool is exactly the
set of images carrying its id.

A many-to-many table (images ↔ grids) was considered and rejected for v1 on
the grounds that grids tend to be long-lived and image curation is per-grid
in practice. Upgrading to M2M later is straightforward.

## API surface

All under `/api/grids`.

| Endpoint                                   | Purpose                                          |
| ------------------------------------------ | ------------------------------------------------ |
| `GET /`                                    | List grids (`?include_devices=true` to embed)    |
| `POST /`                                   | Create grid (`name`, `width_cm`, `height_cm`)    |
| `GET /{id}`                                | Detail, includes placements + midpoints          |
| `PUT /{id}`                                | Rename or resize (re-validates placements)       |
| `DELETE /{id}`                             | Delete; releases claims; clears `target_grid_id` |
| `POST /{id}/devices`                       | Place a device (midpoint or top-left)            |
| `PUT /{id}/devices/{device_id}`            | Move a placement                                 |
| `DELETE /{id}/devices/{device_id}`         | Remove placement; releases its claim if held     |
| `POST /{id}/display` (`{image_id}`)        | Render slices + push to every member device      |
| `POST /{id}/next`                          | Pick next image from grid pool and display       |
| `POST /{id}/release`                       | Clear all claims this grid currently holds       |

The image router also gains a `target_grid_id` filter on `GET /api/images`
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

A 2-display wall:

- Living-room grid: `80 cm × 40 cm`.
- Device A (Inky Impression 13.3", 27.1 × 20.3 cm) mounted at midpoint
  `(20, 20)`.
- Device B (Inky Impression 13.3") mounted at midpoint `(60, 20)`.

```bash
# 1. Create the grid.
curl -X POST localhost:8000/api/grids \
  -H "content-type: application/json" \
  -d '{"name": "living-wall", "width_cm": 80, "height_cm": 40}'
# → {"id": "<grid_id>", ...}

# 2. Place each device.
curl -X POST localhost:8000/api/grids/<grid_id>/devices \
  -H "content-type: application/json" \
  -d '{"device_id": "<device_a_uuid>", "midpoint_x_cm": 20, "midpoint_y_cm": 20}'
curl -X POST localhost:8000/api/grids/<grid_id>/devices \
  -H "content-type: application/json" \
  -d '{"device_id": "<device_b_uuid>", "midpoint_x_cm": 60, "midpoint_y_cm": 20}'

# 3. Upload an image targeted at the grid (UI: pick target grid in the upload form).
#    Or update an existing image:
curl -X PUT localhost:8000/api/images/<image_id> \
  -H "content-type: application/json" \
  -d '{"target_grid_id": "<grid_id>"}'

# 4. Display.
curl -X POST localhost:8000/api/grids/<grid_id>/display \
  -H "content-type: application/json" \
  -d '{"image_id": "<image_id>"}'

# 5. Later, hand the devices back to solo rotation:
curl -X POST localhost:8000/api/grids/<grid_id>/release
```

## Operational notes

- **Overlapping placements are allowed but logged.** Two devices whose
  rectangles intersect on the canvas will both render their respective
  source-image regions; the operator sees a warning in the API log.
- **The grid's `scheduled_next_at` drives the rotation loop.** It's bumped
  to `now + image.display_duration_seconds` whenever a new image is
  displayed; the rotation tick (every 30 s) advances the grid when due.
- **Member devices stay claimed across image transitions.** A grid pulling
  its next image does *not* release devices between images. Use
  `POST /release` (or `DELETE` the grid / placements) to return them to
  solo rotation.
- **Controllers are unchanged.** No grid-specific code lives on the device
  side; a controller just receives a normal display command with a path
  pointing into the `grids/` prefix.

## Out of scope (today)

- Fit modes other than cover.
- Drag-and-drop visual placement editor in the UI (numeric midpoint inputs
  only).
- Many-to-many image-to-grid pools.
- Per-mounting physical-size overrides.
- Bezel-gap / mullion compensation between adjacent panels.
- Auto-detect "this image fits grid X" — image assignment is explicit.
