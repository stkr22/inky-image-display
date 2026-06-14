// Image detail: preview + edit form + "send to device/grid" dialog.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Expansion, NumberField, Slider, TextArea, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError, DeviceNotConnectedError } from '../lib/api'
import { formatDatetime } from '../lib/format'
import { maxDevicePxcm, recommendedDims } from '../lib/quality'
import { imageTitle, mediaUrl, type Device, type Grid, type Image } from '../lib/types'

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
  const [duration, setDuration] = useState<number | ''>(600)
  const [priority, setPriority] = useState(5)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [sendOpen, setSendOpen] = useState(false)

  useEffect(() => {
    if (!image) return
    setTitle(image.title ?? '')
    setDescription(image.description ?? '')
    setAuthor(image.author ?? '')
    setTags(image.tags ?? '')
    setDuration(image.display_duration_seconds ?? 600)
    setPriority(image.priority ?? 5)
  }, [image])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.updateImage(imageId!, {
        title: title || null,
        description: description || null,
        author: author || null,
        tags: tags || null,
        display_duration_seconds: Number(duration) || 600,
        priority,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      notify('Saved', 'positive')
      navigate('/images')
    },
    onError: (err) => notify(`Update failed: ${err instanceof ApiError ? err.detail || err.message : err}`, 'negative'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteImage(imageId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      notify('Deleted', 'positive')
      navigate('/images')
    },
    onError: (err) => notify(`Delete failed: ${err instanceof ApiError ? err.detail || err.message : err}`, 'negative'),
  })

  if (isPending) return <Spinner />
  if (error || !image) return <ErrorNote>Could not load image.</ErrorNote>

  return (
    <>
      <div className="row w-full items-center gap-2">
        <Link to="/images" className="ink-btn ink-btn-flat ink-btn-icon" title="Back to library">
          <span className="material-icons">arrow_back</span>
        </Link>
        <PageHeader eyebrow="Image" title={imageTitle(image)} />
      </div>

      <div className="row w-full gap-5 wrap items-start">
        <div className="bento-tile flex-1" style={{ padding: 16, minWidth: 280 }}>
          <img
            src={mediaUrl(image.storage_path)}
            alt={imageTitle(image)}
            loading="lazy"
            style={{ width: '100%', maxHeight: '72vh', objectFit: 'contain', borderRadius: 12, background: 'var(--ink-field-bg)' }}
          />
        </div>

        <div className="bento-tile" style={{ padding: 20, width: '100%', maxWidth: 420 }}>
          <div className="ink-form-section w-full">
            <span className="ink-eyebrow">Edit</span>
            <TextField label="Title" value={title} onChange={setTitle} />
            <TextArea label="Description" value={description} onChange={setDescription} rows={3} />
            <TextField label="Author" value={author} onChange={setAuthor} />
            <TextField label="Tags (comma-separated)" value={tags} onChange={setTags} />
            <div className="ink-form-row items-end w-full">
              <NumberField label="Duration (s)" value={duration} onChange={setDuration} min={1} step={1} />
              <Slider label="Priority" value={priority} onChange={setPriority} min={1} max={10} />
            </div>
            <Expansion title="Metadata">
              <Metadata image={image} />
            </Expansion>
          </div>
        </div>
      </div>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate('/images')}>
          Cancel
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

// Pick a compatible device or grid and dispatch this image to it. Devices
// require an exact dimension match because e-ink panels can't rescale; grids
// cover-crop anything that meets the densest member device's recommendation.
function SendDialog({ image, onClose }: { image: Image; onClose: () => void }) {
  const notify = useNotify()
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })

  const imgW = image.original_width
  const imgH = image.original_height
  const profileById = new Map((profiles ?? []).map((p) => [p.id, p]))

  const compatibleDevices = (imgW && imgH ? (devices ?? []) : []).filter((device) => {
    const profile = profileById.get(device.device_profile_id)
    if (!profile) return false
    const [targetW, targetH] =
      device.display_orientation === 'portrait' ? [profile.height, profile.width] : [profile.width, profile.height]
    return targetW === imgW && targetH === imgH
  })

  const compatibleGrids = (imgW && imgH ? (grids ?? []) : []).filter((grid) => {
    const maxPxcm = maxDevicePxcm(grid, devices ?? [], profiles ?? [])
    if (maxPxcm == null) return false
    const rec = recommendedDims(grid, maxPxcm)
    return imgW! >= rec.w && imgH! >= rec.h
  })

  const sendToDevice = async (device: Device) => {
    try {
      await api.displayImage(device.device_id, image.id)
    } catch (err) {
      if (err instanceof DeviceNotConnectedError) {
        notify(`${device.device_id} is offline — command dropped`, 'warning')
      } else {
        notify(`Send failed: ${err instanceof ApiError ? err.detail || err.message : err}`, 'negative')
      }
      return
    }
    notify(`Sent to ${device.device_id}`, 'positive')
    onClose()
  }

  const sendToGrid = async (grid: Grid) => {
    try {
      await api.displayGridImage(grid.id, image.id)
    } catch (err) {
      notify(`Send failed: ${err instanceof ApiError ? err.detail || err.message : err}`, 'negative')
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

      {compatibleDevices.length === 0 && compatibleGrids.length === 0 && (
        <span className="ink-small">No compatible devices or grids for this image.</span>
      )}

      {compatibleDevices.length > 0 && (
        <>
          <span className="ink-eyebrow" style={{ marginTop: 8 }}>
            Devices
          </span>
          <div className="w-full gap-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            {compatibleDevices.map((device) => (
              <div
                key={device.id}
                className="ink-device-card"
                style={{ padding: 12, opacity: device.is_online ? 1 : 0.55, cursor: device.is_online ? 'pointer' : 'default' }}
                onClick={device.is_online ? () => sendToDevice(device) : undefined}
              >
                <div className="row items-center justify-between gap-2">
                  <span className="truncate" style={{ fontSize: 14, fontWeight: 500, minWidth: 0 }}>{device.device_id}</span>
                  <Badge tone={device.is_online ? 'ok' : 'muted'}>{device.is_online ? 'Online' : 'Offline'}</Badge>
                </div>
                <span className="ink-small">{device.room || '—'}</span>
                {/* This device's last refresh failed and auto-rotation is paused
                    for it — warn before the operator deliberately sends here. */}
                {device.last_refresh_ok === false && (
                  <div className="row" style={{ marginTop: 4 }}>
                    <Badge tone="warn">Refresh failed</Badge>
                  </div>
                )}
              </div>
            ))}
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
