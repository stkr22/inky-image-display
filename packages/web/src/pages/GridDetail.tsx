// Grid detail: layout preview with device rectangles over the source image,
// placement management, and per-grid image actions with quality hints.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, IntervalInputs, NumberField, SelectField, Switch, TextField, totalSeconds } from '../components/fields'
import { useNotify } from '../components/Toast'
import { EmptyNote, ErrorNote, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatDatetime, formatIntervalSeconds, formatRelative, splitHoursMinutes } from '../lib/format'
import { CROP_NEGLIGIBLE, cropText, imageFit, maxDevicePxcm, recommendedDims, resolutionBand } from '../lib/quality'
import { imageTitle, mediaUrl, type Device, type DeviceProfile, type Grid, type GridPlacement, type Image } from '../lib/types'

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

export function GridDetail() {
  const { gridId } = useParams<{ gridId: string }>()
  const queryClient = useQueryClient()

  const { data: grid, isPending, error } = useQuery({
    queryKey: ['grid', gridId],
    queryFn: () => api.getGrid(gridId!),
    enabled: Boolean(gridId),
  })
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: imageList } = useQuery({ queryKey: ['images', 'grid-pool'], queryFn: () => api.listImages({ limit: 200 }) })
  const images = imageList?.items

  const [previewImageId, setPreviewImageId] = useState<string | null>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['grid', gridId] })
    queryClient.invalidateQueries({ queryKey: ['grids'] })
    queryClient.invalidateQueries({ queryKey: ['images'] })
  }

  const imageById = useMemo(() => new Map((images ?? []).map((img) => [img.id, img])), [images])

  if (isPending) return <Spinner />
  if (error || !grid) return <ErrorNote>Could not load grid.</ErrorNote>

  const previewImage =
    (previewImageId && imageById.get(previewImageId)) ||
    (grid.current_image_id && imageById.get(grid.current_image_id)) ||
    null
  const maxPxcm = maxDevicePxcm(grid, devices ?? [], profiles ?? [])

  return (
    <>
      <GridHeader grid={grid} onChanged={refresh} />
      <CanvasPreview grid={grid} devices={devices ?? []} previewImage={previewImage} maxPxcm={maxPxcm} onChanged={refresh} />
      <Placements grid={grid} devices={devices ?? []} profiles={profiles ?? []} onChanged={refresh} />
      <ImageActions
        grid={grid}
        images={images ?? []}
        poolTotal={imageList?.total ?? 0}
        maxPxcm={maxPxcm}
        previewImageId={previewImageId}
        onPreview={setPreviewImageId}
        onChanged={refresh}
      />
    </>
  )
}

function GridHeader({ grid, onChanged }: { grid: Grid; onChanged: () => void }) {
  const navigate = useNavigate()
  const notify = useNotify()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editOpen, setEditOpen] = useState(false)

  const doDelete = async () => {
    setConfirmDelete(false)
    try {
      await api.deleteGrid(grid.id)
    } catch (err) {
      notify(`Delete failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Grid deleted', 'positive')
    navigate('/displays')
  }

  return (
    <div className="row w-full items-end justify-between wrap gap-3">
      <div className="col gap-0">
        <span className="ink-eyebrow">Grid</span>
        <h2 className="ink-h2">{grid.name}</h2>
        <span className="ink-small">
          Canvas: {grid.width_cm.toFixed(1)} x {grid.height_cm.toFixed(1)} cm
        </span>
        <span className="ink-small">
          Refresh every {formatIntervalSeconds(grid.refresh_interval_seconds)} · next {formatDatetime(grid.scheduled_next_at)} (
          {formatRelative(grid.scheduled_next_at)})
        </span>
      </div>
      <div className="row gap-2 items-center">
        <Link to="/displays" className="ink-small">
          ← Displays
        </Link>
        <Button flat icon="edit" onClick={() => setEditOpen(true)}>
          Edit
        </Button>
        <Button flat danger icon="delete" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        message={`Delete grid '${grid.name}'? Member devices return to solo rotation.`}
        destructive
        confirmLabel="Delete"
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(false)}
      />
      {editOpen && <EditGridDialog grid={grid} onClose={() => setEditOpen(false)} onSaved={onChanged} />}
    </div>
  )
}

function EditGridDialog({ grid, onClose, onSaved }: { grid: Grid; onClose: () => void; onSaved: () => void }) {
  const notify = useNotify()
  const { data: settings } = useQuery({ queryKey: ['app-settings'], queryFn: api.getAppSettings })
  const defaultLabel = settings ? formatIntervalSeconds(settings.default_refresh_seconds) : 'default'

  const [name, setName] = useState(grid.name)
  const [width, setWidth] = useState<number | ''>(grid.width_cm)
  const [height, setHeight] = useState<number | ''>(grid.height_cm)
  const [initialHours, initialMinutes] = splitHoursMinutes(grid.refresh_interval_seconds)
  const [useDefault, setUseDefault] = useState(grid.refresh_interval_seconds == null)
  const [hours, setHours] = useState<number | ''>(initialHours)
  const [minutes, setMinutes] = useState<number | ''>(initialMinutes)

  const submit = async () => {
    const payload: Record<string, unknown> = {}
    if (name && name !== grid.name) payload.name = name
    if (width && Number(width) !== grid.width_cm) payload.width_cm = Number(width)
    if (height && Number(height) !== grid.height_cm) payload.height_cm = Number(height)
    if (useDefault) {
      if (grid.refresh_interval_seconds != null) payload.clear_refresh_interval = true
    } else {
      const total = totalSeconds(hours, minutes)
      if (total <= 0) {
        notify('Pick at least 1 minute, or switch to default.', 'warning')
        return
      }
      if (total !== (grid.refresh_interval_seconds ?? -1)) payload.refresh_interval_seconds = total
    }
    if (Object.keys(payload).length === 0) {
      onClose()
      return
    }
    try {
      await api.updateGrid(grid.id, payload)
    } catch (err) {
      notify(`Update failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Grid updated', 'positive')
    onSaved()
    onClose()
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Edit grid</h3>
      <TextField label="Name" value={name} onChange={setName} />
      <NumberField label="Width (cm)" value={width} onChange={setWidth} min={1} step={1} />
      <NumberField label="Height (cm)" value={height} onChange={setHeight} min={1} step={1} />
      <span className="ink-small">
        Resizing re-validates every placed device — devices whose rectangle would fall off the new canvas reject the change.
      </span>
      <span className="ink-eyebrow">Refresh schedule</span>
      <Switch label={`Use default interval (${defaultLabel})`} checked={useDefault} onChange={setUseDefault} />
      <IntervalInputs hours={hours} minutes={minutes} onHours={setHours} onMinutes={setMinutes} disabled={useDefault} />
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={submit}>
          Save
        </Button>
      </div>
    </Dialog>
  )
}

// Proportional canvas with device rectangles overlaid on the source image.
// background-size: cover + center matches the API's cover-fit crop math, so
// each rectangle frames the region that device actually receives.
function CanvasPreview({
  grid,
  devices,
  previewImage,
  maxPxcm,
  onChanged,
}: {
  grid: Grid
  devices: Device[]
  previewImage: Image | null
  maxPxcm: number | null
  onChanged: () => void
}) {
  const notify = useNotify()
  const placements = grid.devices ?? []
  const deviceById = new Map(devices.map((d) => [d.id, d]))
  const gridW = grid.width_cm
  const gridH = grid.height_cm

  const canvasRef = useRef<HTMLDivElement>(null)
  // Live drag bookkeeping stays in a ref so pointermove only re-renders via
  // the position state below, and pointerup reads the latest coords reliably.
  const dragInfo = useRef<{
    pointerId: number
    startClientX: number
    startClientY: number
    originXCm: number
    originYCm: number
    cmPerPx: number
    xCm: number
    yCm: number
  } | null>(null)
  // Position override for the dragged rectangle. `active: false` means the
  // drop was saved and we are waiting for the refetched grid to catch up.
  const [drag, setDrag] = useState<{ deviceId: string; xCm: number; yCm: number; active: boolean } | null>(null)
  const [saving, setSaving] = useState(false)

  // Clear the saved-drop override once the refetched placement matches it,
  // otherwise the stale override would mask later numeric Move edits.
  useEffect(() => {
    if (!drag || drag.active) return
    const placed = (grid.devices ?? []).find((p) => p.device_id === drag.deviceId)
    if (!placed || (Math.abs(placed.bottom_left_x_cm - drag.xCm) < 0.001 && Math.abs(placed.bottom_left_y_cm - drag.yCm) < 0.001)) {
      setDrag(null)
    }
  }, [grid.devices, drag])

  const startDrag = (event: React.PointerEvent<HTMLDivElement>, placement: GridPlacement) => {
    if (saving) return
    const canvas = canvasRef.current
    if (!canvas) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragInfo.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originXCm: placement.bottom_left_x_cm,
      originYCm: placement.bottom_left_y_cm,
      // Canvas aspect ratio matches the grid, so one scale serves both axes.
      cmPerPx: gridW / canvas.getBoundingClientRect().width,
      xCm: placement.bottom_left_x_cm,
      yCm: placement.bottom_left_y_cm,
    }
    setDrag({ deviceId: placement.device_id, xCm: placement.bottom_left_x_cm, yCm: placement.bottom_left_y_cm, active: true })
  }

  const moveDrag = (event: React.PointerEvent<HTMLDivElement>, placement: GridPlacement) => {
    const info = dragInfo.current
    if (!info || info.pointerId !== event.pointerId) return
    const dxCm = (event.clientX - info.startClientX) * info.cmPerPx
    // Pointer moving down the screen (CSS Y grows down) shrinks the API's
    // bottom-left Y, which grows up — hence the sign flip.
    const dyCm = (event.clientY - info.startClientY) * info.cmPerPx
    info.xCm = Math.min(Math.max(info.originXCm + dxCm, 0), Math.max(0, gridW - placement.width_cm))
    info.yCm = Math.min(Math.max(info.originYCm - dyCm, 0), Math.max(0, gridH - placement.height_cm))
    setDrag({ deviceId: placement.device_id, xCm: info.xCm, yCm: info.yCm, active: true })
  }

  const endDrag = async (event: React.PointerEvent<HTMLDivElement>, placement: GridPlacement) => {
    const info = dragInfo.current
    if (!info || info.pointerId !== event.pointerId) return
    dragInfo.current = null
    const xCm = Math.round(info.xCm * 10) / 10
    const yCm = Math.round(info.yCm * 10) / 10
    if (xCm === Math.round(info.originXCm * 10) / 10 && yCm === Math.round(info.originYCm * 10) / 10) {
      setDrag(null)
      return
    }
    setDrag({ deviceId: placement.device_id, xCm, yCm, active: false })
    setSaving(true)
    try {
      await api.updateDevicePlacement(grid.id, placement.device_id, { bottom_left_x_cm: xCm, bottom_left_y_cm: yCm })
    } catch (err) {
      setDrag(null) // revert to the last server-confirmed position
      notify(`Move failed: ${errMessage(err)}`, 'negative')
      return
    } finally {
      setSaving(false)
    }
    notify('Device moved', 'positive')
    onChanged()
  }

  const cancelDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const info = dragInfo.current
    if (!info || info.pointerId !== event.pointerId) return
    dragInfo.current = null
    setDrag(null)
  }

  const bgStyle = previewImage
    ? {
        backgroundImage: `url('${mediaUrl(previewImage.storage_path, 960)}')`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }
    : { background: 'repeating-linear-gradient(45deg, #f4f5f7, #f4f5f7 12px, #ebedf0 12px, #ebedf0 24px)' }

  return (
    <div className="ink-card" style={{ gap: 10 }}>
      <div className="row w-full items-baseline justify-between">
        <h3 className="ink-h3">Layout preview</h3>
        {previewImage ? (
          <span className="ink-small">Preview: {imageTitle(previewImage)}</span>
        ) : (
          <span className="ink-small">No image selected — use Preview below to pick one.</span>
        )}
      </div>
      <div className="row w-full gap-4 wrap items-start">
        <div className="col gap-1" style={{ flex: '1 1 480px', maxWidth: 720 }}>
          <div
            ref={canvasRef}
            style={{
              width: '100%',
              aspectRatio: `${gridW} / ${gridH}`,
              position: 'relative',
              border: '1px solid var(--ink-border)',
              borderRadius: 8,
              overflow: 'hidden',
              ...bgStyle,
            }}
          >
          {placements.map((placement) => {
            const device = deviceById.get(placement.device_id)
            const label = device?.device_id ?? placement.device_id.slice(0, 8)
            const dragPos = drag && drag.deviceId === placement.device_id ? drag : null
            // API gives bottom-left (Y-up); CSS wants top-left (Y-down).
            const xCm = dragPos ? dragPos.xCm : placement.bottom_left_x_cm
            const yCm = dragPos ? dragPos.yCm : placement.bottom_left_y_cm
            const leftPct = (xCm / gridW) * 100
            const topPct = ((gridH - yCm - placement.height_cm) / gridH) * 100
            return (
              <div
                key={placement.device_id}
                className={`ink-canvas-placement${dragPos?.active ? ' dragging' : ''}${saving ? ' disabled' : ''}`}
                onPointerDown={(e) => startDrag(e, placement)}
                onPointerMove={(e) => moveDrag(e, placement)}
                onPointerUp={(e) => endDrag(e, placement)}
                onPointerCancel={cancelDrag}
                style={{
                  position: 'absolute',
                  left: `${leftPct}%`,
                  top: `${topPct}%`,
                  width: `${(placement.width_cm / gridW) * 100}%`,
                  height: `${(placement.height_cm / gridH) * 100}%`,
                  border: '2px solid rgba(11, 18, 32, 0.75)',
                  boxShadow: '0 0 0 1px rgba(255, 255, 255, 0.7) inset',
                  display: 'flex',
                  alignItems: 'flex-end',
                  padding: '4px 6px',
                }}
              >
                <span
                  style={{
                    background: 'rgba(11, 18, 32, 0.78)',
                    color: '#fff',
                    fontSize: 11,
                    padding: '2px 6px',
                    borderRadius: 4,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {label}
                </span>
              </div>
            )
          })}
          </div>
          {placements.length > 0 && <span className="ink-small">Drag a panel to reposition it.</span>}
        </div>
        {previewImage && <SourceWithUsedRegion image={previewImage} grid={grid} />}
      </div>
      <RecommendationLine grid={grid} maxPxcm={maxPxcm} previewImage={previewImage} />
    </div>
  )
}

// Thumbnail of the full source image with the kept region outlined; the
// dimmed strips show exactly what the cover-fit crops away.
function SourceWithUsedRegion({ image, grid }: { image: Image; grid: Grid }) {
  const imgW = image.original_width
  const imgH = image.original_height
  if (!imgW || !imgH) {
    return (
      <div className="col gap-1" style={{ flex: '0 0 240px', minWidth: 200 }}>
        <span className="ink-eyebrow">Source image</span>
        <span className="ink-small">(dimensions unknown)</span>
      </div>
    )
  }
  const canvasAspect = grid.width_cm / grid.height_cm
  const imageAspect = imgW / imgH
  let usedLeft = 0
  let usedTop = 0
  let usedW = 100
  let usedH = 100
  if (imageAspect > canvasAspect) {
    usedW = (canvasAspect / imageAspect) * 100
    usedLeft = (100 - usedW) / 2
  } else {
    usedH = (imageAspect / canvasAspect) * 100
    usedTop = (100 - usedH) / 2
  }

  const strips: Array<{ left: number; top: number; width: number; height: number }> = []
  if (usedLeft > 0) strips.push({ left: 0, top: 0, width: usedLeft, height: 100 })
  if (100 - (usedLeft + usedW) > 0) strips.push({ left: usedLeft + usedW, top: 0, width: 100 - (usedLeft + usedW), height: 100 })
  if (usedTop > 0) strips.push({ left: usedLeft, top: 0, width: usedW, height: usedTop })
  if (100 - (usedTop + usedH) > 0) strips.push({ left: usedLeft, top: usedTop + usedH, width: usedW, height: 100 - (usedTop + usedH) })

  const croppedPct = 100 - (usedW * usedH) / 100

  return (
    <div className="col gap-1" style={{ flex: '0 0 240px', minWidth: 200 }}>
      <span className="ink-eyebrow">Source image</span>
      <div
        style={{
          position: 'relative',
          width: '100%',
          aspectRatio: `${imgW} / ${imgH}`,
          border: '1px solid var(--ink-border)',
          borderRadius: 6,
          overflow: 'hidden',
          backgroundImage: `url('${mediaUrl(image.storage_path, 480)}')`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      >
        {strips.map((strip, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: `${strip.left}%`,
              top: `${strip.top}%`,
              width: `${strip.width}%`,
              height: `${strip.height}%`,
              background: 'rgba(11, 18, 32, 0.55)',
            }}
          />
        ))}
        <div
          style={{
            position: 'absolute',
            left: `${usedLeft}%`,
            top: `${usedTop}%`,
            width: `${usedW}%`,
            height: `${usedH}%`,
            border: '2px solid rgba(255, 255, 255, 0.95)',
            boxShadow: '0 0 0 1px rgba(11, 18, 32, 0.4)',
          }}
        />
      </div>
      {croppedPct < CROP_NEGLIGIBLE * 100 ? (
        <span className="ink-small">Aspect matches the canvas — nothing cropped.</span>
      ) : (
        <span className="ink-small">
          {Math.round(croppedPct)}% cropped ({imageAspect > canvasAspect ? 'horizontal' : 'vertical'})
        </span>
      )}
    </div>
  )
}

function RecommendationLine({ grid, maxPxcm, previewImage }: { grid: Grid; maxPxcm: number | null; previewImage: Image | null }) {
  if (maxPxcm == null) {
    return <span className="ink-small">Place a device to see recommended image dimensions.</span>
  }
  const rec = recommendedDims(grid, maxPxcm)
  const base = `Recommended ≥ ${rec.w}x${rec.h} px (densest device: ${Math.round(maxPxcm)} px/cm).`
  if (previewImage) {
    const fit = imageFit(previewImage.original_width ?? 0, previewImage.original_height ?? 0, grid)
    if (fit) {
      const ratio = maxPxcm > 0 ? fit.effectivePxcm / maxPxcm : 0
      const band = resolutionBand(ratio)
      return (
        <span className="ink-small" style={{ color: band.color }}>
          {base} Current: {previewImage.original_width}x{previewImage.original_height} px →{' '}
          {Math.round(fit.effectivePxcm)} px/cm effective ({ratio.toFixed(2)}x target, {band.band}).
        </span>
      )
    }
  }
  return <span className="ink-small">{base}</span>
}

// --- Placements ----------------------------------------------------------------

function deviceDimsCm(device: Device, profileById: Map<string, DeviceProfile>): [number, number] {
  const profile = profileById.get(device.device_profile_id)
  if (!profile) return [0, 0]
  return device.display_orientation === 'portrait'
    ? [profile.physical_height_cm, profile.physical_width_cm]
    : [profile.physical_width_cm, profile.physical_height_cm]
}

function Placements({
  grid,
  devices,
  profiles,
  onChanged,
}: {
  grid: Grid
  devices: Device[]
  profiles: DeviceProfile[]
  onChanged: () => void
}) {
  const notify = useNotify()
  const [addOpen, setAddOpen] = useState(false)
  const [movePlacement, setMovePlacement] = useState<GridPlacement | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<GridPlacement | null>(null)

  const placements = grid.devices ?? []
  const placedIds = new Set(placements.map((p) => p.device_id))
  const unplaced = devices.filter((d) => !placedIds.has(d.id))
  const deviceById = new Map(devices.map((d) => [d.id, d]))
  const profileById = new Map(profiles.map((p) => [p.id, p]))

  const remove = async (placement: GridPlacement) => {
    setConfirmRemove(null)
    try {
      await api.removeDeviceFromGrid(grid.id, placement.device_id)
    } catch (err) {
      notify(`Remove failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Device removed', 'positive')
    onChanged()
  }

  return (
    <div className="ink-card">
      <div className="row w-full items-center justify-between">
        <h3 className="ink-h3">Devices</h3>
        <Button primary icon="add" disabled={unplaced.length === 0} onClick={() => setAddOpen(true)}>
          Add device
        </Button>
      </div>
      {placements.length === 0 && <EmptyNote>No devices placed yet.</EmptyNote>}
      {placements.map((placement) => {
        const device = deviceById.get(placement.device_id)
        return (
          <div
            key={placement.device_id}
            className="row w-full items-center justify-between"
            style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 10 }}
          >
            <div className="col gap-0">
              <span className="ink-body">{device?.device_id ?? placement.device_id.slice(0, 8)}</span>
              <span className="ink-small">
                bottom-left ({placement.bottom_left_x_cm.toFixed(1)}, {placement.bottom_left_y_cm.toFixed(1)}) cm ·{' '}
                {placement.width_cm.toFixed(1)} x {placement.height_cm.toFixed(1)} cm
              </span>
            </div>
            <div className="row gap-2">
              <Button flat icon="open_with" onClick={() => setMovePlacement(placement)}>
                Move
              </Button>
              <Button flat danger icon="delete" onClick={() => setConfirmRemove(placement)}>
                Remove
              </Button>
            </div>
          </div>
        )
      })}
      {addOpen && (
        <AddDeviceDialog
          grid={grid}
          unplaced={unplaced}
          profileById={profileById}
          onClose={() => setAddOpen(false)}
          onDone={onChanged}
        />
      )}
      {movePlacement && (
        <MoveDeviceDialog grid={grid} placement={movePlacement} onClose={() => setMovePlacement(null)} onDone={onChanged} />
      )}
      <ConfirmDialog
        open={confirmRemove != null}
        message={
          confirmRemove
            ? `Remove '${deviceById.get(confirmRemove.device_id)?.device_id ?? confirmRemove.device_id.slice(0, 8)}' from this grid? The device returns to solo rotation.`
            : ''
        }
        destructive
        confirmLabel="Remove"
        onConfirm={() => confirmRemove && remove(confirmRemove)}
        onCancel={() => setConfirmRemove(null)}
      />
    </div>
  )
}

function AddDeviceDialog({
  grid,
  unplaced,
  profileById,
  onClose,
  onDone,
}: {
  grid: Grid
  unplaced: Device[]
  profileById: Map<string, DeviceProfile>
  onClose: () => void
  onDone: () => void
}) {
  const notify = useNotify()
  const [deviceId, setDeviceId] = useState('')
  const [x, setX] = useState<number | ''>(0)
  const [y, setY] = useState<number | ''>(0)

  const device = unplaced.find((d) => d.id === deviceId)
  const [devW, devH] = device ? deviceDimsCm(device, profileById) : [0, 0]

  const submit = async () => {
    if (!deviceId) {
      notify('Pick a device', 'warning')
      return
    }
    try {
      await api.addDeviceToGrid(grid.id, { device_id: deviceId, bottom_left_x_cm: x, bottom_left_y_cm: y })
    } catch (err) {
      notify(`Add failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Device placed', 'positive')
    onDone()
    onClose()
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Place device</h3>
      <span className="ink-small">
        Origin (0, 0) is the grid's bottom-left corner. Canvas: {grid.width_cm.toFixed(1)} x {grid.height_cm.toFixed(1)} cm.
      </span>
      <SelectField
        label="Device"
        value={deviceId}
        onChange={setDeviceId}
        options={[{ value: '', label: 'Pick a device…' }, ...unplaced.map((d) => ({ value: d.id, label: d.device_id }))]}
      />
      <NumberField label="Width position (cm)" value={x} onChange={setX} step={0.5} />
      <span className="ink-small">
        {device
          ? `Allowed: 0 to ${Math.max(0, grid.width_cm - devW).toFixed(1)} cm (device width ${devW.toFixed(1)} cm)`
          : 'Pick a device to see allowed range.'}
      </span>
      <NumberField label="Height position (cm)" value={y} onChange={setY} step={0.5} />
      <span className="ink-small">
        {device
          ? `Allowed: 0 to ${Math.max(0, grid.height_cm - devH).toFixed(1)} cm (device height ${devH.toFixed(1)} cm)`
          : 'Pick a device to see allowed range.'}
      </span>
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={submit}>
          Place
        </Button>
      </div>
    </Dialog>
  )
}

function MoveDeviceDialog({
  grid,
  placement,
  onClose,
  onDone,
}: {
  grid: Grid
  placement: GridPlacement
  onClose: () => void
  onDone: () => void
}) {
  const notify = useNotify()
  const [x, setX] = useState<number | ''>(placement.bottom_left_x_cm)
  const [y, setY] = useState<number | ''>(placement.bottom_left_y_cm)

  const submit = async () => {
    try {
      await api.updateDevicePlacement(grid.id, placement.device_id, { bottom_left_x_cm: x, bottom_left_y_cm: y })
    } catch (err) {
      notify(`Move failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Device moved', 'positive')
    onDone()
    onClose()
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Move device</h3>
      <span className="ink-small">
        Origin (0, 0) is the grid's bottom-left corner. Canvas: {grid.width_cm.toFixed(1)} x {grid.height_cm.toFixed(1)} cm.
      </span>
      <NumberField label="Width position (cm)" value={x} onChange={setX} step={0.5} />
      <span className="ink-small">
        Allowed: 0 to {Math.max(0, grid.width_cm - placement.width_cm).toFixed(1)} cm (device width{' '}
        {placement.width_cm.toFixed(1)} cm)
      </span>
      <NumberField label="Height position (cm)" value={y} onChange={setY} step={0.5} />
      <span className="ink-small">
        Allowed: 0 to {Math.max(0, grid.height_cm - placement.height_cm).toFixed(1)} cm (device height{' '}
        {placement.height_cm.toFixed(1)} cm)
      </span>
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={submit}>
          Save
        </Button>
      </div>
    </Dialog>
  )
}

// --- Images for this grid -----------------------------------------------------------

function ImageActions({
  grid,
  images,
  poolTotal,
  maxPxcm,
  previewImageId,
  onPreview,
  onChanged,
}: {
  grid: Grid
  images: Image[]
  poolTotal: number
  maxPxcm: number | null
  previewImageId: string | null
  onPreview: (id: string) => void
  onChanged: () => void
}) {
  const notify = useNotify()
  const gridImages = images.filter((img) => img.target_grid_id === grid.id)

  const release = async () => {
    try {
      await api.releaseGrid(grid.id)
    } catch (err) {
      notify(`Release failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Grid released — devices return to solo.', 'positive')
    onChanged()
  }

  const display = async (image: Image) => {
    try {
      await api.displayGridImage(grid.id, image.id)
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify(`Showing on ${grid.name}`, 'positive')
    onChanged()
  }

  return (
    <div className="ink-card">
      <div className="row w-full items-center justify-between">
        <h3 className="ink-h3">Images for this grid</h3>
        <Button flat icon="logout" onClick={release}>
          Release devices
        </Button>
      </div>
      {poolTotal > images.length && (
        <span className="ink-small">
          Showing first {images.length} of {poolTotal} images — images beyond this pool are not listed here.
        </span>
      )}
      {gridImages.length === 0 && (
        <EmptyNote>No images target this grid. Upload an image and pick this grid as target.</EmptyNote>
      )}
      <div className="w-full gap-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
        {gridImages.map((image) => {
          const isPreviewed = previewImageId === image.id
          const fit = imageFit(image.original_width ?? 0, image.original_height ?? 0, grid)
          const ratio = fit && maxPxcm ? fit.effectivePxcm / maxPxcm : null
          const band = ratio != null ? resolutionBand(ratio) : null
          return (
            <div
              key={image.id}
              style={{
                border: `2px solid ${isPreviewed ? 'var(--ink-accent)' : 'var(--ink-border)'}`,
                borderRadius: 12,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <img
                src={mediaUrl(image.storage_path, 480)}
                loading="lazy"
                alt={imageTitle(image)}
                style={{ width: '100%', aspectRatio: '4/3', objectFit: 'cover' }}
              />
              <div className="col gap-1" style={{ padding: 12 }}>
                <span className="ink-body truncate">{imageTitle(image)}</span>
                {fit ? (
                  <div className="row w-full gap-2 items-center">
                    <span className="ink-small truncate" style={{ flex: '1 1 auto' }}>
                      {fit.imageAspect.toFixed(2)}:1 vs grid {fit.canvasAspect.toFixed(2)}:1 — {cropText(fit)}
                    </span>
                    {band && ratio != null && (
                      <span className="ink-res-badge" style={{ color: band.color }}>
                        {band.glyph} {band.band} ({ratio.toFixed(2)}x)
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="ink-small">Resolution unknown</span>
                )}
                <div className="row w-full gap-2 wrap">
                  <Button flat icon="visibility" onClick={() => onPreview(image.id)}>
                    Preview
                  </Button>
                  <Button primary icon="play_arrow" onClick={() => display(image)}>
                    Display now
                  </Button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
