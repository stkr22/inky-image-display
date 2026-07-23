// Upload form with drag-and-drop, client-side preview, automatic portrait
// detection from the decoded image, and a live quality hint vs the target grid.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { CropDialog } from '../components/CropDialog'
import { Button, Icon, SelectField, Switch, TextArea, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { BackLink, PageHeader } from '../components/ui'
import { api, errMessage } from '../lib/api'
import type { CroppedResult } from '../lib/crop'
import { cropText, imageFit, maxDevicePxcm, recommendedDims, resolutionBand } from '../lib/quality'
import type { Grid } from '../lib/types'
import { useUnsavedGuard } from '../lib/useUnsavedGuard'

interface SelectedFile {
  file: File
  previewUrl: string
  width: number | null
  height: number | null
}

export function ImageUpload() {
  const navigate = useNavigate()
  const notify = useNotify()
  const fileInput = useRef<HTMLInputElement>(null)

  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })
  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })

  const [selected, setSelected] = useState<SelectedFile | null>(null)
  // The as-picked file, kept so re-crops always start from full quality.
  const [original, setOriginal] = useState<{ file: File; previewUrl: string } | null>(null)
  const [cropOpen, setCropOpen] = useState(false)
  const [dragover, setDragover] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [author, setAuthor] = useState('')
  const [tags, setTags] = useState('')
  const [portrait, setPortrait] = useState(false)
  const [targetGrid, setTargetGrid] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploaded, setUploaded] = useState(false)
  // Server-rendered Spectra 6 simulation of the currently selected (possibly
  // cropped) bytes, so surprises show up before the upload — not on the wall.
  const [einkPreview, setEinkPreview] = useState(false)
  const [einkUrl, setEinkUrl] = useState<string | null>(null)
  const [einkBusy, setEinkBusy] = useState(false)

  const pickFile = (file: File) => {
    const previewUrl = URL.createObjectURL(file)
    setOriginal({ file, previewUrl })
    const probe = new Image()
    probe.onload = () => {
      setSelected({ file, previewUrl, width: probe.naturalWidth, height: probe.naturalHeight })
      // Auto-detect orientation; the switch stays editable for overrides.
      setPortrait(probe.naturalHeight > probe.naturalWidth)
    }
    probe.onerror = () => setSelected({ file, previewUrl, width: null, height: null })
    probe.src = previewUrl
    if (!title) setTitle(file.name.replace(/\.[^.]+$/, ''))
  }

  const applyCrop = (result: CroppedResult, isPortrait: boolean) => {
    setSelected({
      file: result.file,
      previewUrl: URL.createObjectURL(result.file),
      width: result.width,
      height: result.height,
    })
    setPortrait(isPortrait)
    setCropOpen(false)
    notify(`Cropped to ${result.width}x${result.height} px`, 'positive')
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragover(false)
    const file = event.dataTransfer.files[0]
    if (file) pickFile(file)
  }

  // Re-render the e-ink simulation whenever the toggle is on and the file
  // (or its crop) changes; revoke stale object URLs to avoid leaks.
  useEffect(() => {
    if (!einkPreview || !selected) {
      setEinkUrl(null)
      return
    }
    let cancelled = false
    setEinkBusy(true)
    api
      .einkPreviewUpload(selected.file)
      .then((blob) => {
        if (!cancelled) setEinkUrl(URL.createObjectURL(blob))
      })
      .catch(() => {
        if (!cancelled) {
          setEinkPreview(false)
          notify('E-ink preview failed — showing the original.', 'warning')
        }
      })
      .finally(() => {
        if (!cancelled) setEinkBusy(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [einkPreview, selected])

  useEffect(() => () => void (einkUrl && URL.revokeObjectURL(einkUrl)), [einkUrl])

  const submit = async () => {
    if (!selected) {
      setError('Choose a file first.')
      return
    }
    const metadata: Record<string, unknown> = {
      source_name: 'manual',
      title: title || null,
      description: description || null,
      author: author || null,
      tags: tags || null,
      is_portrait: portrait,
    }
    if (targetGrid) metadata.target_grid_id = targetGrid
    setBusy(true)
    try {
      await api.uploadImage(selected.file, metadata)
    } catch (err) {
      setError(`Upload failed: ${errMessage(err)}`)
      setBusy(false)
      return
    }
    setUploaded(true)
    allowLeave()
    notify('Uploaded', 'positive')
    navigate('/images')
  }

  // A picked (and possibly cropped) file is real work worth guarding; the
  // post-upload navigation must not prompt (allowLeave below).
  const allowLeave = useUnsavedGuard(selected !== null && !uploaded)

  const grid = grids?.find((g) => g.id === targetGrid)

  return (
    <>
      <div className="row w-full items-center gap-2">
        <BackLink to="/images" title="Back to library" />
        <PageHeader eyebrow="Library / new" title="Upload image" />
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">File</span>
          <span className="ink-small">Drop or pick a photo to upload (JPG, PNG, WEBP, HEIC).</span>
          <div
            className={`ink-dropzone ${dragover ? 'is-dragover' : ''}`}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragover(true)
            }}
            onDragLeave={() => setDragover(false)}
            onDrop={onDrop}
          >
            {selected ? (
              <>
                <img src={einkPreview && einkUrl ? einkUrl : selected.previewUrl} alt="Preview" />
                <span className="ink-small">
                  {selected.file.name}
                  {selected.width && selected.height ? ` · ${selected.width}x${selected.height} px` : ''}
                  {einkPreview && einkUrl ? ' · e-ink simulation' : ''}
                </span>
              </>
            ) : (
              <>
                <Icon name="add_photo_alternate" style={{ fontSize: 32 }} />
                <span>Drop an image here, or click to choose</span>
              </>
            )}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept=".jpg,.jpeg,.png,.webp,.heic"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) pickFile(file)
            }}
          />
          {selected && (
            <div className="row gap-2 wrap items-center">
              <Button ghost icon="crop" disabled={!selected.width} onClick={() => setCropOpen(true)}>
                Crop…
              </Button>
              {original && selected.file !== original.file && (
                <Button flat icon="undo" onClick={() => pickFile(original.file)}>
                  Reset to original
                </Button>
              )}
              <Switch
                label={einkBusy ? 'E-ink preview (rendering…)' : 'E-ink preview'}
                checked={einkPreview}
                onChange={setEinkPreview}
              />
            </div>
          )}
        </div>
      </div>

      {cropOpen && original && (
        <CropDialog
          sourceUrl={original.previewUrl}
          fileName={original.file.name}
          profiles={profiles ?? []}
          targetGrid={grid ?? null}
          onApply={applyCrop}
          onClose={() => setCropOpen(false)}
        />
      )}

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Metadata</span>
          <TextField label="Title" value={title} onChange={setTitle} />
          <TextArea label="Description" value={description} onChange={setDescription} rows={3} />
          <div className="ink-form-row w-full">
            <TextField label="Author" value={author} onChange={setAuthor} />
            <TextField label="Tags (comma-separated)" value={tags} onChange={setTags} />
          </div>
          <Switch label="Portrait (for portrait-oriented devices)" checked={portrait} onChange={setPortrait} />
          <SelectField
            label="Target grid"
            value={targetGrid}
            onChange={setTargetGrid}
            options={[
              { value: '', label: '(solo rotation)' },
              ...(grids ?? []).map((g) => ({
                value: g.id,
                label: `${g.name} (${Math.round(g.width_cm)}x${Math.round(g.height_cm)} cm)`,
              })),
            ]}
          />
          {grid && <QualityHint grid={grid} selected={selected} maxPxcm={maxDevicePxcm(grid, devices ?? [], profiles ?? [])} />}
        </div>
      </div>

      <span className="ink-form-error">{error}</span>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate('/images')}>
          Cancel
        </Button>
        <Button primary icon="upload" onClick={submit} disabled={busy}>
          {busy ? 'Uploading…' : 'Upload'}
        </Button>
      </div>
    </>
  )
}

function QualityHint({
  grid,
  selected,
  maxPxcm,
}: {
  grid: Grid
  selected: SelectedFile | null
  maxPxcm: number | null
}) {
  if (!selected?.width || !selected.height) {
    return <span className="ink-small">Pick a file to see how it fits this grid.</span>
  }
  const fit = imageFit(selected.width, selected.height, grid)
  if (!fit) return <span className="ink-small">Resolution unknown.</span>

  const rec = maxPxcm ? recommendedDims(grid, maxPxcm) : null
  const ratio = maxPxcm ? fit.effectivePxcm / maxPxcm : null
  const band = ratio != null ? resolutionBand(ratio) : null

  return (
    <div className="col w-full gap-1">
      <div className="row w-full items-center gap-2">
        <span className="ink-small" style={{ flex: '1 1 auto' }}>
          {selected.width}x{selected.height} px · {fit.imageAspect.toFixed(2)}:1 vs grid {fit.canvasAspect.toFixed(2)}:1 —{' '}
          {cropText(fit)}
        </span>
        {band && ratio != null && (
          <span className="ink-res-badge" style={{ color: band.color }}>
            {band.glyph} {band.band} ({ratio.toFixed(2)}x)
          </span>
        )}
      </div>
      {rec && maxPxcm ? (
        <span className="ink-small">
          Recommended ≥ {rec.w}x{rec.h} px (densest device: {Math.round(maxPxcm)} px/cm).
        </span>
      ) : (
        <span className="ink-small">Place a device on this grid to compute a recommended resolution.</span>
      )}
    </div>
  )
}
