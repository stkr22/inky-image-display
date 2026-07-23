// Image detail: preview + edit form + "send to device/grid" dialog.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Expansion, NumberField, Switch, TextArea, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { BackLink, Badge, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError, DeviceNotConnectedError, errMessage } from '../lib/api'
import { formatDatetime } from '../lib/format'
import { maxDevicePxcm, recommendedDims } from '../lib/quality'
import { einkPreviewUrl, imageTitle, mediaUrl, type Device, type DeviceProfile, type Grid, type Image } from '../lib/types'
import { useUnsavedGuard } from '../lib/useUnsavedGuard'

export function ImageDetail() {
  const { imageId } = useParams<{ imageId: string }>()
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()

  const { data: image, isPending, error } = useQuery({
    queryKey: ['image', imageId],
    queryFn: () => api.getImage(imageId!),
    enabled: Boolean(imageId),
  })

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [author, setAuthor] = useState('')
  const [tags, setTags] = useState('')
  // Per-image hold: null on the wire means "rotate on the device interval".
  const [holdEnabled, setHoldEnabled] = useState(false)
  const [duration, setDuration] = useState<number | ''>(3600)
  const [excluded, setExcluded] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [sendOpen, setSendOpen] = useState(false)
  // Toggle between the plain photo and the server-side Spectra 6 simulation.
  const [einkPreview, setEinkPreview] = useState(false)

  useEffect(() => {
    if (!image) return
    setTitle(image.title ?? '')
    setDescription(image.description ?? '')
    setAuthor(image.author ?? '')
    setTags(image.tags ?? '')
    setHoldEnabled(image.display_duration_seconds != null)
    setDuration(image.display_duration_seconds ?? 3600)
    setExcluded(image.excluded_from_rotation)
  }, [image])

  const saveMutation = useMutation({
    mutationFn: () => {
      if (holdEnabled && (Number(duration) || 0) < 1) {
        return Promise.reject(new ApiError(0, 'Hold time must be at least 1 second.'))
      }
      return api.updateImage(imageId!, {
        title: title || null,
        description: description || null,
        author: author || null,
        tags: tags || null,
        display_duration_seconds: holdEnabled ? Number(duration) : null,
        excluded_from_rotation: excluded,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['image', imageId] })
      notify('Saved', 'positive')
    },
    onError: (err) => notify(`Update failed: ${errMessage(err)}`, 'negative'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteImage(imageId!),
    onSuccess: () => {
      // Deleting intentionally discards edits — don't prompt on the redirect.
      allowLeave()
      queryClient.invalidateQueries({ queryKey: ['images'] })
      notify('Deleted', 'positive')
      navigate('/images')
    },
    onError: (err) => notify(`Delete failed: ${errMessage(err)}`, 'negative'),
  })

  // Dirty vs the loaded record.
  const dirty =
    Boolean(image) &&
    (title !== (image?.title ?? '') ||
      description !== (image?.description ?? '') ||
      author !== (image?.author ?? '') ||
      tags !== (image?.tags ?? '') ||
      excluded !== (image?.excluded_from_rotation ?? false) ||
      holdEnabled !== (image?.display_duration_seconds != null) ||
      (holdEnabled && Number(duration) !== image?.display_duration_seconds))
  const allowLeave = useUnsavedGuard(dirty)

  if (isPending) return <Spinner />
  if (error || !image) return <ErrorNote>Could not load image.</ErrorNote>

  return (
    <>
      <div className="row w-full items-center gap-2">
        <BackLink to="/images" title="Back to library" />
        <PageHeader eyebrow="Image" title={imageTitle(image)} />
        {image.excluded_from_rotation && <Badge tone="muted">Excluded from rotation</Badge>}
      </div>

      <div className="row w-full gap-5 wrap items-start">
        <div className="bento-tile flex-1" style={{ padding: 16, minWidth: 280 }}>
          <img
            src={einkPreview ? einkPreviewUrl(image.id) : mediaUrl(image.storage_path)}
            alt={imageTitle(image)}
            loading="lazy"
            style={{ width: '100%', maxHeight: '72vh', objectFit: 'contain', borderRadius: 12, background: 'var(--ink-field-bg)' }}
          />
          <div className="row w-full items-center justify-between wrap gap-2">
            <Switch label="E-ink preview" checked={einkPreview} onChange={setEinkPreview} />
            {einkPreview && (
              <span className="ink-small" style={{ opacity: 0.7 }}>
                Simulated Spectra 6 rendering — the same six-ink dither the panel applies.
              </span>
            )}
          </div>
        </div>

        <div className="bento-tile" style={{ padding: 20, width: '100%', maxWidth: 420 }}>
          <div className="ink-form-section w-full">
            <span className="ink-eyebrow">Edit</span>
            <TextField label="Title" value={title} onChange={setTitle} />
            <TextArea label="Description" value={description} onChange={setDescription} rows={3} />
            <TextField label="Author" value={author} onChange={setAuthor} />
            <TextField label="Tags (comma-separated)" value={tags} onChange={setTags} />
            <Switch label="Hold on screen for a custom time" checked={holdEnabled} onChange={setHoldEnabled} />
            {holdEnabled && (
              <>
                <NumberField label="Hold time (s)" value={duration} onChange={setDuration} min={1} step={1} />
                <span className="ink-small" style={{ opacity: 0.7 }}>
                  Once shown, this image stays up this long before the device rotates — overriding the device
                  interval for this image only.
                </span>
              </>
            )}
            <Switch label="Exclude from rotation" checked={excluded} onChange={setExcluded} />
            {excluded && (
              <span className="ink-small" style={{ opacity: 0.7 }}>
                Never picked automatically (solo or grid). Manual sends still work.
              </span>
            )}
            <Expansion title="Metadata">
              <Metadata image={image} />
            </Expansion>
          </div>
        </div>
      </div>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate('/images')}>
          Back
        </Button>
        <Button flat danger icon="delete" onClick={() => setConfirmDelete(true)}>
          Delete
        </Button>
        <Button ghost icon="send" onClick={() => setSendOpen(true)}>
          Send to…
        </Button>
        <Button primary icon="save" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          Save
        </Button>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        message={`Delete image '${imageTitle(image)}'?`}
        destructive
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false)
          deleteMutation.mutate()
        }}
        onCancel={() => setConfirmDelete(false)}
      />

      {sendOpen && <SendDialog image={image} onClose={() => setSendOpen(false)} />}
    </>
  )
}

function Metadata({ image }: { image: Image }) {
  const rows: Array<[string, string]> = [
    ['ID', image.id],
    ['Source', image.source_name || '?'],
  ]
  if (image.source_id) rows.push(['Source ID', image.source_id])
  if (image.sync_job_name) rows.push(['Sync job', image.sync_job_name])
  rows.push(
    ['Dimensions', `${image.original_width ?? '?'}x${image.original_height ?? '?'}`],
    ['Created', formatDatetime(image.created_at)],
    ['Last displayed', formatDatetime(image.last_displayed_at)],
  )
  const isHttp = image.source_url?.startsWith('http://') || image.source_url?.startsWith('https://')
  return (
    <div className="col w-full gap-2" style={{ padding: '8px 0' }}>
      {rows.map(([label, value]) => (
        <div key={label} className="row w-full items-baseline gap-3">
          <span className="ink-small" style={{ width: 110, flexShrink: 0 }}>
            {label}
          </span>
          <span className="ink-meta-value">{value}</span>
        </div>
      ))}
      {image.source_url && (
        <div className="row w-full items-baseline gap-3">
          <span className="ink-small" style={{ width: 110, flexShrink: 0 }}>
            Source URL
          </span>
          {isHttp ? (
            <a
              href={image.source_url}
              target="_blank"
              rel="noreferrer"
              className="ink-meta-value"
              style={{ color: 'var(--ink-accent)' }}
            >
              {image.source_url}
            </a>
          ) : (
            <span className="ink-meta-value">{image.source_url}</span>
          )}
        </div>
      )}
    </div>
  )
}

// Pick a device or grid and dispatch this image to it. Exact-size matches
// send as-is; other devices are offered with a "cropped to fit" note and the
// API cover-crops a derived copy server-side (fit=auto) — previously those
// devices were silently hidden, which read as "no compatible devices" with
// no explanation. Grids cover-crop anything that meets the densest member
// device's recommendation.
function SendDialog({ image, onClose }: { image: Image; onClose: () => void }) {
  const notify = useNotify()
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })

  const imgW = image.original_width
  const imgH = image.original_height
  const profileById = new Map((profiles ?? []).map((p) => [p.id, p]))

  const isExactMatch = (device: Device): boolean => {
    const profile = profileById.get(device.device_profile_id)
    if (!profile || !imgW || !imgH) return false
    const [targetW, targetH] =
      device.display_orientation === 'portrait' ? [profile.height, profile.width] : [profile.width, profile.height]
    return targetW === imgW && targetH === imgH
  }

  const allDevices = imgW && imgH ? (devices ?? []) : []

  const compatibleGrids = (imgW && imgH ? (grids ?? []) : []).filter((grid) => {
    const maxPxcm = maxDevicePxcm(grid, devices ?? [], profiles ?? [])
    if (maxPxcm == null) return false
    const rec = recommendedDims(grid, maxPxcm)
    return imgW! >= rec.w && imgH! >= rec.h
  })

  const sendToDevice = async (device: Device, exact: boolean) => {
    try {
      await api.displayImage(device.device_id, image.id, exact ? 'exact' : 'auto')
    } catch (err) {
      if (err instanceof DeviceNotConnectedError) {
        notify(`${device.device_id} is offline — command dropped`, 'warning')
      } else {
        notify(`Send failed: ${errMessage(err)}`, 'negative')
      }
      return
    }
    notify(exact ? `Sent to ${device.device_id}` : `Cropped to fit and sent to ${device.device_id}`, 'positive')
    onClose()
  }

  const sendToGrid = async (grid: Grid) => {
    try {
      await api.displayGridImage(grid.id, image.id)
    } catch (err) {
      notify(`Send failed: ${errMessage(err)}`, 'negative')
      return
    }
    notify(`Sent to grid ${grid.name}`, 'positive')
    onClose()
  }

  return (
    <Dialog open onClose={onClose} style={{ width: 'min(760px, 95vw)' }}>
      <div className="col gap-0">
        <span className="ink-eyebrow">Send</span>
        <h3 className="ink-h3">{imageTitle(image)}</h3>
        <span className="ink-small">
          {imgW ?? '?'}x{imgH ?? '?'} · {image.is_portrait ? 'portrait' : 'landscape'}
        </span>
      </div>

      {allDevices.length === 0 && compatibleGrids.length === 0 && (
        <span className="ink-small">No devices or grids available for this image.</span>
      )}

      {allDevices.length > 0 && (
        <>
          <span className="ink-eyebrow" style={{ marginTop: 8 }}>
            Devices
          </span>
          <div className="w-full gap-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            {allDevices.map((device) => {
              const exact = isExactMatch(device)
              const profile = profileById.get(device.device_profile_id)
              return (
                <DeviceSendCard
                  key={device.id}
                  device={device}
                  profile={profile}
                  exact={exact}
                  onSend={() => sendToDevice(device, exact)}
                />
              )
            })}
          </div>
        </>
      )}

      {compatibleGrids.length > 0 && (
        <>
          <span className="ink-eyebrow" style={{ marginTop: 8 }}>
            Grids
          </span>
          <div className="w-full gap-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            {compatibleGrids.map((grid) => (
              <div key={grid.id} className="ink-device-card" style={{ padding: 12 }} onClick={() => sendToGrid(grid)}>
                <span style={{ fontSize: 14, fontWeight: 500 }}>{grid.name}</span>
                <span className="ink-small">
                  {Math.round(grid.width_cm)}x{Math.round(grid.height_cm)} cm · {grid.devices?.length ?? 0} device(s)
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="row w-full justify-end gap-2" style={{ marginTop: 8 }}>
        <Button flat onClick={onClose}>
          Close
        </Button>
      </div>
    </Dialog>
  )
}

function DeviceSendCard({
  device,
  profile,
  exact,
  onSend,
}: {
  device: Device
  profile: DeviceProfile | undefined
  exact: boolean
  onSend: () => void
}) {
  return (
    <div
      className="ink-device-card"
      style={{ padding: 12, opacity: device.is_online ? 1 : 0.55, cursor: device.is_online ? 'pointer' : 'default' }}
      onClick={device.is_online ? onSend : undefined}
    >
      <div className="row items-center justify-between gap-2">
        <span className="truncate" style={{ fontSize: 14, fontWeight: 500, minWidth: 0 }}>{device.device_id}</span>
        <Badge tone={device.is_online ? 'ok' : 'muted'}>{device.is_online ? 'Online' : 'Offline'}</Badge>
      </div>
      <span className="ink-small">{device.room || '—'}</span>
      {!exact && profile && (
        <span className="ink-small" style={{ opacity: 0.8 }}>
          Will be cover-cropped to {profile.width}x{profile.height}
        </span>
      )}
      {/* This device's last refresh failed and auto-rotation is paused
          for it — warn before the operator deliberately sends here. */}
      {device.refresh_state === 'failed_retrying' && (
        <div className="row" style={{ marginTop: 4 }}>
          <Badge tone="warn">Refresh failed — retrying</Badge>
        </div>
      )}
      {device.refresh_state === 'failed_stale' && (
        <div className="row" style={{ marginTop: 4 }}>
          <Badge tone="danger">Refresh failing — check power</Badge>
        </div>
      )}
    </div>
  )
}
