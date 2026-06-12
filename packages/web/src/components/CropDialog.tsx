// Crop dialog used by the upload page: aspect presets come from the chosen
// target grid and the seeded device profiles. Panel presets output the
// panel's exact pixel dimensions (e-ink needs an exact match to be
// sendable); the grid preset keeps the crop's native resolution so the
// grid retains every available pixel.

import { useMemo, useState } from 'react'
import Cropper, { type Area } from 'react-easy-crop'
import { cropImage, type CroppedResult } from '../lib/crop'
import type { DeviceProfile, Grid } from '../lib/types'
import { Dialog } from './Dialog'
import { Button, SelectField } from './fields'

interface AspectPreset {
  key: string
  label: string
  aspect: number
  // Exact output dims (panel presets); undefined keeps native crop resolution.
  output?: { width: number; height: number }
  isPortrait: boolean
}

function buildPresets(profiles: DeviceProfile[], targetGrid: Grid | null): AspectPreset[] {
  const presets: AspectPreset[] = []
  if (targetGrid) {
    presets.push({
      key: 'grid',
      label: `Target grid — ${targetGrid.name} (${targetGrid.width_cm.toFixed(0)}x${targetGrid.height_cm.toFixed(0)} cm)`,
      aspect: targetGrid.width_cm / targetGrid.height_cm,
      isPortrait: targetGrid.width_cm < targetGrid.height_cm,
    })
  }
  for (const profile of profiles) {
    presets.push({
      key: `${profile.id}-landscape`,
      label: `${profile.name} · landscape (${profile.width}x${profile.height})`,
      aspect: profile.width / profile.height,
      output: { width: profile.width, height: profile.height },
      isPortrait: false,
    })
    presets.push({
      key: `${profile.id}-portrait`,
      label: `${profile.name} · portrait (${profile.height}x${profile.width})`,
      aspect: profile.height / profile.width,
      output: { width: profile.height, height: profile.width },
      isPortrait: true,
    })
  }
  return presets
}

export function CropDialog({
  sourceUrl,
  fileName,
  profiles,
  targetGrid,
  onApply,
  onClose,
}: {
  sourceUrl: string
  fileName: string
  profiles: DeviceProfile[]
  targetGrid: Grid | null
  onApply: (result: CroppedResult, isPortrait: boolean) => void
  onClose: () => void
}) {
  const presets = useMemo(() => buildPresets(profiles, targetGrid), [profiles, targetGrid])
  const [presetKey, setPresetKey] = useState(presets[0]?.key ?? '')
  const preset = presets.find((p) => p.key === presetKey) ?? presets[0]
  const [crop, setCrop] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [cropPixels, setCropPixels] = useState<Area | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const apply = async () => {
    if (!cropPixels || !preset) return
    setBusy(true)
    try {
      const result = await cropImage(sourceUrl, cropPixels, fileName, preset.output)
      onApply(result, preset.isPortrait)
    } catch (err) {
      setError(String(err))
      setBusy(false)
    }
  }

  if (!preset) return null

  return (
    <Dialog open onClose={onClose} style={{ width: 'min(820px, 95vw)' }}>
      <div className="col gap-0">
        <span className="ink-eyebrow">Crop</span>
        <h3 className="ink-h3">Fit the image to its target</h3>
      </div>
      <SelectField
        label="Aspect / target"
        value={preset.key}
        onChange={setPresetKey}
        options={presets.map((p) => ({ value: p.key, label: p.label }))}
      />
      <div className="ink-crop-area">
        <Cropper
          image={sourceUrl}
          crop={crop}
          zoom={zoom}
          aspect={preset.aspect}
          onCropChange={setCrop}
          onZoomChange={setZoom}
          onCropComplete={(_area, areaPixels) => setCropPixels(areaPixels)}
        />
      </div>
      <div className="ink-slider-row">
        <span className="ink-field-label" style={{ minWidth: 44 }}>
          Zoom
        </span>
        <input type="range" min={1} max={4} step={0.01} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
      </div>
      <span className="ink-small">
        {preset.output
          ? `Output: exactly ${preset.output.width}x${preset.output.height} px — directly sendable to that panel.`
          : 'Output keeps the native resolution of the cropped region.'}
      </span>
      {error && <span className="ink-form-error">{error}</span>}
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary icon="crop" onClick={apply} disabled={busy || !cropPixels}>
          {busy ? 'Cropping…' : 'Apply crop'}
        </Button>
      </div>
    </Dialog>
  )
}
