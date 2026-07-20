// Grid detail: layout preview with device rectangles over the source image,
// tile-layout editing, the display-job content schedule (when generated
// content takes over the panels), and per-grid image actions with quality
// hints.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, IntervalInputs, NumberField, Switch, TextField, totalSeconds } from '../components/fields'
import { GridLayoutEditor, layoutRowsFromGrid, type LayoutRows } from '../components/GridLayoutEditor'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, ErrorNote, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatDatetime, formatIntervalSeconds, formatRelative, splitHoursMinutes } from '../lib/format'
import { CROP_NEGLIGIBLE, cropText, imageFit, maxDevicePxcm, recommendedDims, resolutionBand } from '../lib/quality'
import { imageTitle, mediaUrl, type Device, type Grid, type Image } from '../lib/types'

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
      <GridHeader grid={grid} devices={devices ?? []} onChanged={refresh} />
      <CanvasPreview grid={grid} devices={devices ?? []} previewImage={previewImage} maxPxcm={maxPxcm} />
      <QueueCard grid={grid} onChanged={refresh} />
      <DisplayScheduleCard grid={grid} onChanged={refresh} />
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

function GridHeader({ grid, devices, onChanged }: { grid: Grid; devices: Device[]; onChanged: () => void }) {
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
          Canvas: {grid.width_cm.toFixed(1)} x {grid.height_cm.toFixed(1)} cm · {grid.devices?.length ?? 0} device(s)
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
      {editOpen && <EditGridDialog grid={grid} devices={devices} onClose={() => setEditOpen(false)} onSaved={onChanged} />}
    </div>
  )
}

function EditGridDialog({
  grid,
  devices,
  onClose,
  onSaved,
}: {
  grid: Grid
  devices: Device[]
  onClose: () => void
  onSaved: () => void
}) {
  const notify = useNotify()
  const { data: settings } = useQuery({ queryKey: ['app-settings'], queryFn: api.getAppSettings })
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const defaultLabel = settings ? formatIntervalSeconds(settings.default_refresh_seconds) : 'default'

  const initialRows = useMemo(() => layoutRowsFromGrid(grid.devices ?? []), [grid.devices])
  const [name, setName] = useState(grid.name)
  const [rows, setRows] = useState<LayoutRows>(initialRows)
  const [initialHours, initialMinutes] = splitHoursMinutes(grid.refresh_interval_seconds)
  const [useDefault, setUseDefault] = useState(grid.refresh_interval_seconds == null)
  const [hours, setHours] = useState<number | ''>(initialHours)
  const [minutes, setMinutes] = useState<number | ''>(initialMinutes)

  const submit = async () => {
    const cleanRows = rows.filter((row) => row.length > 0)
    if (cleanRows.length === 0) {
      notify('A grid needs at least one device.', 'warning')
      return
    }
    const payload: Record<string, unknown> = {}
    if (name && name !== grid.name) payload.name = name
    if (JSON.stringify(cleanRows) !== JSON.stringify(layoutRowsFromGrid(grid.devices ?? []))) payload.rows = cleanRows
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
      <span className="ink-eyebrow">Layout</span>
      <GridLayoutEditor rows={rows} onChange={setRows} devices={devices} profiles={profiles ?? []} excludeGridId={grid.id} />
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

// --- Display-job content schedule ------------------------------------------------

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Explicit 24h hour/minute inputs: the native time input renders 12h on
// AM/PM-locale browsers, and the operator wants 24h everywhere.
function DisplayTimeFields({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const [hour = 8, minute = 0] = value.split(':').map((piece) => Number(piece) || 0)
  const pad = (n: number) => String(n).padStart(2, '0')
  const clamp = (n: number | '', max: number) => Math.min(Math.max(Number(n) || 0, 0), max)
  return (
    <>
      <NumberField
        label="Show at (hour, 24h)"
        value={hour}
        onChange={(v) => onChange(`${pad(clamp(v, 23))}:${pad(minute)}`)}
        min={0}
        max={23}
        disabled={disabled}
        className="flex-1"
      />
      <NumberField
        label="Minute"
        value={minute}
        onChange={(v) => onChange(`${pad(hour)}:${pad(clamp(v, 59))}`)}
        min={0}
        max={59}
        disabled={disabled}
        className="flex-1"
      />
    </>
  )
}

// The grid's daily display schedule: when the newest generated group
// front-runs the queue, and for how long. What is generated (and its
// cadence) lives on the job pages; the live queue state is the card above.
function DisplayScheduleCard({ grid, onChanged }: { grid: Grid; onChanged: () => void }) {
  const notify = useNotify()
  const { data: jobs } = useQuery({ queryKey: ['display-jobs'], queryFn: api.listDisplayJobs })
  const targetingJobs = (jobs ?? []).filter((job) => job.target_grid_id === grid.id)

  const [enabled, setEnabled] = useState(grid.display_schedule_enabled)
  const [displayTime, setDisplayTime] = useState(grid.display_time)
  const [weekdayMask, setWeekdayMask] = useState(grid.display_weekday_mask)
  const [timezone, setTimezone] = useState(grid.display_timezone)
  const [untilReleased, setUntilReleased] = useState(grid.display_duration_seconds === null)
  const [durationMinutes, setDurationMinutes] = useState<number | ''>(
    grid.display_duration_seconds ? Math.round(grid.display_duration_seconds / 60) : 60,
  )
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      const durationSeconds = untilReleased ? null : Math.max(Number(durationMinutes) || 0, 1) * 60
      await api.updateGrid(grid.id, {
        display_schedule_enabled: enabled,
        display_time: displayTime,
        display_weekday_mask: weekdayMask,
        display_timezone: timezone,
        display_duration_seconds: durationSeconds,
        clear_display_duration: untilReleased,
      })
      notify('Display schedule saved.', 'positive')
      onChanged()
    } catch (err) {
      notify(`Save failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ink-card" style={{ gap: 12 }}>
      <div className="row w-full items-center gap-3 wrap">
        <h3 className="ink-h3">Daily schedule</h3>
      </div>
      <span className="ink-small">
        {targetingJobs.length === 0 ? (
          <>
            No display job targets this grid yet — create one on the{' '}
            <Link to="/jobs?tab=display" style={{ color: 'var(--ink-accent)' }}>
              Jobs page
            </Link>
            .
          </>
        ) : (
          <>
            At the chosen time the newest group generated by{' '}
            {targetingJobs.map((job, index) => (
              <span key={job.id}>
                {index > 0 && ', '}
                <Link to={`/display-jobs/${job.id}`} style={{ color: 'var(--ink-accent)' }}>
                  {job.name}
                </Link>
              </span>
            ))}{' '}
            takes over the panels.
          </>
        )}
      </span>
      <Switch checked={enabled} onChange={setEnabled} label="Show automatically every day" />
      <div className="row gap-3 w-full wrap">
        <DisplayTimeFields value={displayTime} onChange={setDisplayTime} disabled={!enabled} />
        <TextField
          label="Timezone (IANA)"
          value={timezone}
          onChange={setTimezone}
          placeholder="Europe/Berlin"
          disabled={!enabled}
          className="flex-1"
        />
      </div>
      <div className="row gap-2 wrap">
        {WEEKDAYS.map((day, index) => {
          const selected = Boolean(weekdayMask & (1 << index))
          return (
            <Button
              key={day}
              flat={!selected}
              primary={selected}
              disabled={!enabled}
              onClick={() => setWeekdayMask((mask) => mask ^ (1 << index))}
            >
              {day}
            </Button>
          )
        })}
      </div>
      <div className="row gap-3 w-full items-end wrap">
        <Switch checked={untilReleased} onChange={setUntilReleased} label="Show until released manually" />
        {!untilReleased && (
          <NumberField
            label="Duration (minutes)"
            value={durationMinutes}
            onChange={setDurationMinutes}
            min={1}
            className="flex-1"
          />
        )}
      </div>
      <div className="row w-full justify-end">
        <Button primary onClick={save} disabled={busy}>
          Save schedule
        </Button>
      </div>
    </div>
  )
}

// --- Content queue -----------------------------------------------------------------

// What plays next on this grid: groups and loose pool images in predicted
// playback order. Fresh entries play first in the order set here (arrow
// buttons persist queue positions); once everything has been shown the
// least recently shown entry replays.
function QueueCard({ grid, onChanged }: { grid: Grid; onChanged: () => void }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: queue } = useQuery({
    queryKey: ['grid-queue', grid.id],
    queryFn: () => api.getGridQueue(grid.id),
    refetchInterval: 15_000,
  })
  const { data: status } = useQuery({
    queryKey: ['grid-display-status', grid.id],
    queryFn: () => api.getGridDisplayStatus(grid.id),
    refetchInterval: 15_000,
  })
  const [busy, setBusy] = useState(false)
  const entries = queue ?? []

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['grid-queue', grid.id] })
    queryClient.invalidateQueries({ queryKey: ['grid-display-status', grid.id] })
    onChanged()
  }

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      notify(label, 'positive')
      refresh()
    } catch (err) {
      notify(`Failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const move = async (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= entries.length) return
    const next = [...entries]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    try {
      await api.reorderGridQueue(
        grid.id,
        next.map((entry) => ({ kind: entry.kind, id: entry.id })),
      )
      refresh()
    } catch (err) {
      notify(`Reorder failed: ${errMessage(err)}`, 'negative')
    }
  }

  const held = status?.hold_until != null
  return (
    <div className="ink-card" style={{ gap: 12 }}>
      <div className="row w-full items-center gap-3 wrap">
        <h3 className="ink-h3">Up next</h3>
        {status?.group_name && (
          <span className="ink-small">
            Now showing “{status.group_name}”
            {status.frame_count > 1 ? ` (frame ${status.frame + 1}/${status.frame_count})` : ''}
          </span>
        )}
        {held && <Badge tone="accent">Held</Badge>}
        <div className="flex-1" />
        <Button
          flat
          icon="skip_next"
          disabled={busy || entries.length === 0}
          onClick={() => act('Advanced to the next entry.', () => api.nextGridContent(grid.id))}
        >
          Next
        </Button>
        <Button
          danger
          disabled={busy || (!held && !status?.group_id)}
          onClick={() => act('Released — panels updated immediately.', () => api.releaseGrid(grid.id))}
        >
          Release
        </Button>
      </div>
      {status && status.slots.length > 0 && (
        <div className="row w-full gap-3 wrap">
          {status.slots.map((slot) => (
            <span key={`${slot.row}:${slot.col}`} className="ink-small">
              <Badge tone={slot.is_online ? 'ok' : 'warn'} /> {slot.device_id}: {slot.current_title ?? '—'}
            </span>
          ))}
        </div>
      )}
      {entries.length === 0 && (
        <EmptyNote>The queue is empty — add images to this grid or create a group for it.</EmptyNote>
      )}
      {entries.map((entry, index) => (
        <div
          key={`${entry.kind}:${entry.id}`}
          className="row w-full items-center gap-3 wrap"
          style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 10 }}
        >
          <span className="ink-small" style={{ width: 24, textAlign: 'right' }}>
            {index + 1}.
          </span>
          {entry.storage_path && (
            <img
              src={mediaUrl(entry.storage_path, 240)}
              alt=""
              style={{ width: 56, height: 42, objectFit: 'cover', borderRadius: 6 }}
            />
          )}
          <div className="col gap-0" style={{ flex: '1 1 auto', minWidth: 160 }}>
            <span className="ink-body truncate">
              {entry.name ?? 'Untitled'} {entry.is_current && <Badge tone="ok">showing</Badge>}
            </span>
            <span className="ink-small">
              {entry.kind === 'group' ? `Group · ${entry.frame_count} frame(s)` : 'Image'} ·{' '}
              {entry.last_displayed_at ? `shown ${formatRelative(entry.last_displayed_at)}` : 'not shown yet'}
            </span>
          </div>
          <Button flat round icon="arrow_upward" title="Earlier" disabled={index === 0} onClick={() => move(index, -1)} />
          <Button
            flat
            round
            icon="arrow_downward"
            title="Later"
            disabled={index === entries.length - 1}
            onClick={() => move(index, 1)}
          />
          <Button
            flat
            round
            icon="play_arrow"
            title="Show now"
            disabled={busy}
            onClick={() =>
              act(
                'Showing now.',
                entry.kind === 'group'
                  ? () => api.displayGridGroup(grid.id, entry.id)
                  : () => api.displayGridImage(grid.id, entry.id),
              )
            }
          />
        </div>
      ))}
    </div>
  )
}

// Proportional canvas with device rectangles overlaid on the source image.
// background-size: cover + center matches the API's cover-fit crop math, so
// each rectangle frames the region that device actually receives. Placements
// are computed from the tile layout — edit the layout to change them.
function CanvasPreview({
  grid,
  devices,
  previewImage,
  maxPxcm,
}: {
  grid: Grid
  devices: Device[]
  previewImage: Image | null
  maxPxcm: number | null
}) {
  const placements = grid.devices ?? []
  const deviceById = new Map(devices.map((d) => [d.id, d]))
  const gridW = grid.width_cm
  const gridH = grid.height_cm

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
            {placements.length === 0 && <EmptyNote>No devices in this grid — edit the layout to add panels.</EmptyNote>}
            {placements.map((placement) => {
              const device = deviceById.get(placement.device_id)
              const label = device?.device_id ?? placement.device_id.slice(0, 8)
              // API gives bottom-left (Y-up); CSS wants top-left (Y-down).
              const leftPct = (placement.bottom_left_x_cm / gridW) * 100
              const topPct = ((gridH - placement.bottom_left_y_cm - placement.height_cm) / gridH) * 100
              return (
                <div
                  key={placement.device_id}
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
    return <span className="ink-small">Add a device to the layout to see recommended image dimensions.</span>
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
