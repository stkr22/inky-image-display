// Unified display page: upcoming schedule queue, device wall, grids list.
// The schedule auto-refreshes every 15s to match the rotation loop's tick.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Icon, IntervalInputs, NumberField, Switch, TextField, totalSeconds } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError, DeviceNotConnectedError } from '../lib/api'
import { formatDatetime, formatIntervalSeconds, formatRelative, splitHoursMinutes } from '../lib/format'
import { imageTitle, mediaUrl, type Device, type DeviceProfile, type Grid, type ScheduleEntry } from '../lib/types'

export function Displays() {
  return (
    <>
      <ScheduleSection />
      <div style={{ height: 32 }} />
      <DevicesSection />
      <div style={{ height: 32 }} />
      <GridsSection />
    </>
  )
}

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

// --- Schedule -------------------------------------------------------------

function ScheduleSection() {
  const { data: entries, refetch, isPending } = useQuery({
    queryKey: ['schedule'],
    queryFn: () => api.getScheduleUpcoming(20),
    refetchInterval: 15_000,
  })

  return (
    <section className="col w-full gap-3">
      <PageHeader
        eyebrow="Upcoming"
        title="Schedule"
        actions={
          <Button flat round icon="refresh" title="Refresh" onClick={() => refetch()} />
        }
      />
      <span className="ink-small">
        Ordered by next refresh time. Devices currently driven by a grid are hidden — the grid entry represents them.
      </span>
      {isPending && <Spinner />}
      {entries?.length === 0 && <EmptyNote>Nothing scheduled yet.</EmptyNote>}
      <div className="col w-full gap-2">
        {entries?.map((entry, index) => <ScheduleRow key={`${entry.kind}-${entry.id}`} position={index + 1} entry={entry} />)}
      </div>
    </section>
  )
}

function ScheduleRow({ position, entry }: { position: number; entry: ScheduleEntry }) {
  const target = entry.kind === 'grid' ? `/grids/${entry.id}` : '/displays'
  return (
    <Link
      to={target}
      className="w-full"
      style={{
        padding: '14px 16px',
        background: 'var(--ink-surface)',
        border: '1px solid var(--ink-border)',
        borderRadius: 14,
        display: 'flex',
        gap: 16,
        alignItems: 'center',
      }}
    >
      <span className="ink-numeric" style={{ minWidth: 32, opacity: 0.6 }}>
        #{position}
      </span>
      <Icon name={entry.kind === 'device' ? 'devices' : 'grid_view'} style={{ opacity: 0.7 }} />
      <div className="col gap-0 flex-1">
        <span className="ink-body truncate">{entry.name}</span>
        <span className="ink-small">
          {entry.kind} · every {formatIntervalSeconds(entry.effective_interval_seconds)}
        </span>
      </div>
      <div className="col gap-0 items-end">
        <span className="ink-body" style={{ fontWeight: 500 }}>
          {formatRelative(entry.scheduled_next_at)}
        </span>
        <span className="ink-small">{formatDatetime(entry.scheduled_next_at)}</span>
      </div>
    </Link>
  )
}

// --- Devices ----------------------------------------------------------------

function DevicesSection() {
  const { data: devices, refetch, isPending } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const profileById = new Map((profiles ?? []).map((p) => [p.id, p]))

  return (
    <section className="col w-full gap-3">
      <PageHeader
        eyebrow="Wall"
        title="Devices"
        actions={<Button flat round icon="refresh" title="Refresh" onClick={() => refetch()} />}
      />
      {isPending && <Spinner />}
      {devices?.length === 0 && <EmptyNote>No devices registered yet.</EmptyNote>}
      {devices?.map((device) => (
        <DeviceCard key={device.id} device={device} profile={profileById.get(device.device_profile_id)} />
      ))}
    </section>
  )
}

function DeviceCard({ device, profile }: { device: Device; profile: DeviceProfile | undefined }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [confirmClear, setConfirmClear] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const currentImage = device.current_image

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['devices'] })

  const doNext = async () => {
    try {
      const result = await api.nextImage(device.device_id)
      notify(`Showing: ${result.title || result.image_id}`)
      refresh()
    } catch (err) {
      if (err instanceof DeviceNotConnectedError) notify(`${device.device_id} is offline — command dropped`, 'warning')
      else notify(`Next failed: ${errMessage(err)}`, 'negative')
    }
  }

  const doClear = async () => {
    setConfirmClear(false)
    try {
      await api.clearDevice(device.device_id)
      notify(`${device.device_id} cleared`, 'positive')
      refresh()
    } catch (err) {
      if (err instanceof DeviceNotConnectedError) notify(`${device.device_id} is offline — command dropped`, 'warning')
      else notify(`Clear failed: ${errMessage(err)}`, 'negative')
    }
  }

  const profileSummary = profile ? `${profile.name} (${profile.width}x${profile.height})` : '(unknown profile)'

  return (
    <div className="ink-card" style={{ padding: 20, borderRadius: 20, gap: 16 }}>
      <div className="ink-device-summary">
        <div className="col gap-2 ink-device-summary-media">
          {currentImage ? (
            <>
              <img className="ink-device-image" style={{ borderRadius: 10 }} src={mediaUrl(currentImage.storage_path, 480)} loading="lazy" alt={imageTitle(currentImage)} />
              <span className="ink-small truncate">{imageTitle(currentImage)}</span>
            </>
          ) : (
            <div className="ink-device-image-empty" style={{ borderRadius: 10 }}>
              <span className="ink-small">No image displayed</span>
            </div>
          )}
        </div>
        <div className="col gap-2 ink-device-summary-info">
          <div className="row items-center gap-3 wrap">
            <h3 className="ink-h3 break-words">{device.device_id}</h3>
            <Badge tone={device.is_online ? 'ok' : 'muted'}>
              {device.is_online ? 'Online' : `Offline since ${formatDatetime(device.last_seen)}`}
            </Badge>
            {/* A failed refresh is invisible from the online flag alone — a
                stuck display keeps acking and stays "Online". Surface it. */}
            {device.last_refresh_ok === false && <Badge tone="warn">Refresh failed</Badge>}
          </div>
          {device.last_refresh_ok === false && (
            <span className="ink-small break-words" style={{ color: 'var(--ink-warn)' }}>
              Last refresh failed{device.last_error_at ? ` ${formatRelative(device.last_error_at)}` : ''}
              {device.last_error ? `: ${device.last_error}` : ''}
            </span>
          )}
          <span className="ink-small break-words">{device.room || '(no room)'}</span>
          <span className="ink-small break-words">
            {profileSummary} · {device.display_orientation}
          </span>
          <span className="ink-small break-words">Displayed since {formatDatetime(device.displayed_since)}</span>
          <span className="ink-small break-words">
            Next scheduled {formatDatetime(device.scheduled_next_at)} ({formatRelative(device.scheduled_next_at)})
          </span>
          <span className="ink-small break-words">Refresh every {formatIntervalSeconds(device.refresh_interval_seconds)}</span>
        </div>
      </div>
      <div className="row w-full gap-2 wrap" style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 14 }}>
        <Button primary icon="skip_next" disabled={!device.is_online} onClick={doNext}>
          Next
        </Button>
        {/* Schedule editing is independent of online state — operators often
            dial cadence on a device that's currently offline. */}
        <Button flat icon="schedule" onClick={() => setScheduleOpen(true)}>
          Schedule
        </Button>
        <Button flat danger icon="clear" disabled={!device.is_online} onClick={() => setConfirmClear(true)}>
          Clear
        </Button>
      </div>

      <ConfirmDialog
        open={confirmClear}
        message={`Clear the display on ${device.device_id}?`}
        destructive
        confirmLabel="Clear"
        onConfirm={doClear}
        onCancel={() => setConfirmClear(false)}
      />
      {scheduleOpen && <ScheduleDialog device={device} onClose={() => setScheduleOpen(false)} onSaved={refresh} />}
    </div>
  )
}

// "Use default" sends clear_refresh_interval=true so the server resets the
// override to NULL rather than ambiguously storing 0.
function ScheduleDialog({ device, onClose, onSaved }: { device: Device; onClose: () => void; onSaved: () => void }) {
  const notify = useNotify()
  const { data: settings } = useQuery({ queryKey: ['app-settings'], queryFn: api.getAppSettings })
  const defaultLabel = settings ? formatIntervalSeconds(settings.default_refresh_seconds) : 'default'

  const [initialHours, initialMinutes] = splitHoursMinutes(device.refresh_interval_seconds)
  const [useDefault, setUseDefault] = useState(device.refresh_interval_seconds == null)
  const [hours, setHours] = useState<number | ''>(initialHours)
  const [minutes, setMinutes] = useState<number | ''>(initialMinutes)

  const submit = async () => {
    let payload: Record<string, unknown>
    if (useDefault) {
      payload = { clear_refresh_interval: true }
    } else {
      const total = totalSeconds(hours, minutes)
      if (total <= 0) {
        notify('Pick at least 1 minute, or switch to default.', 'warning')
        return
      }
      payload = { refresh_interval_seconds: total }
    }
    try {
      await api.updateDevice(device.device_id, payload)
    } catch (err) {
      notify(`Update failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify('Schedule updated', 'positive')
    onSaved()
    onClose()
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Schedule for {device.device_id}</h3>
      <Switch label={`Use default interval (${defaultLabel})`} checked={useDefault} onChange={setUseDefault} />
      <IntervalInputs hours={hours} minutes={minutes} onHours={setHours} onMinutes={setMinutes} disabled={useDefault} />
      <span className="ink-small">Rotation cadence applied after the next refresh tick.</span>
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

// --- Grids ----------------------------------------------------------------------

function GridsSection() {
  const queryClient = useQueryClient()
  const { data: grids, refetch, isPending } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <section className="col w-full gap-3">
      <PageHeader
        eyebrow="Wall"
        title="Grids"
        actions={
          <>
            <Button primary icon="add" title="Create grid" onClick={() => setCreateOpen(true)} />
            <Button flat round icon="refresh" title="Refresh" onClick={() => refetch()} />
          </>
        }
      />
      {isPending && <Spinner />}
      {grids?.length === 0 && <EmptyNote>No grids yet — create one to start.</EmptyNote>}
      {grids?.map((grid) => <GridRow key={grid.id} grid={grid} />)}
      {createOpen && (
        <CreateGridDialog
          onClose={() => setCreateOpen(false)}
          onCreated={() => queryClient.invalidateQueries({ queryKey: ['grids'] })}
        />
      )}
    </section>
  )
}

function GridRow({ grid }: { grid: Grid }) {
  return (
    <Link
      to={`/grids/${grid.id}`}
      className="w-full row items-center justify-between"
      style={{
        padding: 20,
        background: 'var(--ink-surface)',
        border: '1px solid var(--ink-border)',
        borderRadius: 20,
        boxShadow: '0 1px 2px rgba(11,18,32,0.04)',
      }}
    >
      <div className="col gap-0">
        <h3 className="ink-h3">{grid.name}</h3>
        <span className="ink-small">
          {grid.width_cm.toFixed(1)} x {grid.height_cm.toFixed(1)} cm
        </span>
      </div>
      <span className="ink-small">{grid.devices?.length ?? 0} device(s)</span>
    </Link>
  )
}

function CreateGridDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const notify = useNotify()
  const [name, setName] = useState('')
  const [width, setWidth] = useState<number | ''>(80)
  const [height, setHeight] = useState<number | ''>(40)

  const mutation = useMutation({
    mutationFn: () => api.createGrid({ name, width_cm: width, height_cm: height }),
    onSuccess: () => {
      notify('Grid created', 'positive')
      onCreated()
      onClose()
    },
    onError: (err) => notify(`Create failed: ${errMessage(err)}`, 'negative'),
  })

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">New grid</h3>
      <TextField label="Name" value={name} onChange={setName} />
      <NumberField label="Width (cm)" value={width} onChange={setWidth} min={1} step={1} />
      <NumberField label="Height (cm)" value={height} onChange={setHeight} min={1} step={1} />
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          Create
        </Button>
      </div>
    </Dialog>
  )
}
