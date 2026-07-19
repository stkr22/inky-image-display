// Tile-based grid layout editor: arrange devices into rows, everything else
// (canvas size, cm placements) is computed server-side from device profiles.
// The preview mirrors the server's layout rule — rows stacked top-down, each
// row centred horizontally, shorter panels centred vertically in their row.

import { useQuery } from '@tanstack/react-query'
import { Button, SelectField } from './fields'
import { api } from '../lib/api'
import type { Device, DeviceProfile } from '../lib/types'

export type LayoutRows = string[][]

export function layoutRowsFromGrid(placements: Array<{ device_id: string; row: number; col: number }>): LayoutRows {
  const rows: LayoutRows = []
  for (const p of [...placements].sort((a, b) => a.row - b.row || a.col - b.col)) {
    while (rows.length <= p.row) rows.push([])
    rows[p.row].push(p.device_id)
  }
  return rows.filter((row) => row.length > 0)
}

function orientedDimsCm(device: Device, profileById: Map<string, DeviceProfile>): [number, number] {
  const profile = profileById.get(device.device_profile_id)
  if (!profile) return [0, 0]
  return device.display_orientation === 'portrait'
    ? [profile.physical_height_cm, profile.physical_width_cm]
    : [profile.physical_width_cm, profile.physical_height_cm]
}

export function GridLayoutEditor({
  rows,
  onChange,
  devices,
  profiles,
  excludeGridId,
}: {
  rows: LayoutRows
  onChange: (rows: LayoutRows) => void
  devices: Device[]
  profiles: DeviceProfile[]
  // Devices already placed in this grid stay selectable (editing its layout).
  excludeGridId?: string
}) {
  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })
  const takenElsewhere = new Set(
    (grids ?? [])
      .filter((g) => g.id !== excludeGridId)
      .flatMap((g) => (g.devices ?? []).map((p) => p.device_id)),
  )
  const used = new Set(rows.flat())
  const available = devices.filter((d) => !takenElsewhere.has(d.id) && !used.has(d.id))
  const deviceById = new Map(devices.map((d) => [d.id, d]))
  const profileById = new Map(profiles.map((p) => [p.id, p]))

  const update = (mutate: (next: LayoutRows) => void) => {
    const next = rows.map((row) => [...row])
    mutate(next)
    onChange(next)
  }

  const addDevice = (rowIndex: number, deviceId: string) => {
    if (!deviceId) return
    update((next) => next[rowIndex].push(deviceId))
  }
  const removeDevice = (rowIndex: number, colIndex: number) =>
    update((next) => {
      next[rowIndex].splice(colIndex, 1)
      if (next[rowIndex].length === 0) next.splice(rowIndex, 1)
    })
  const moveDevice = (rowIndex: number, colIndex: number, dir: -1 | 1) =>
    update((next) => {
      const row = next[rowIndex]
      const target = colIndex + dir
      if (target < 0 || target >= row.length) return
      ;[row[colIndex], row[target]] = [row[target], row[colIndex]]
    })
  const moveRow = (rowIndex: number, dir: -1 | 1) =>
    update((next) => {
      const target = rowIndex + dir
      if (target < 0 || target >= next.length) return
      ;[next[rowIndex], next[target]] = [next[target], next[rowIndex]]
    })

  return (
    <div className="col w-full gap-3">
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="col w-full gap-2" style={{ border: '1px solid var(--ink-border)', borderRadius: 8, padding: 10 }}>
          <div className="row w-full items-center justify-between">
            <span className="ink-eyebrow">Row {rowIndex + 1}</span>
            <div className="row gap-1">
              <Button flat round icon="arrow_upward" title="Move row up" disabled={rowIndex === 0} onClick={() => moveRow(rowIndex, -1)} />
              <Button
                flat
                round
                icon="arrow_downward"
                title="Move row down"
                disabled={rowIndex === rows.length - 1}
                onClick={() => moveRow(rowIndex, 1)}
              />
            </div>
          </div>
          <div className="row w-full gap-2 wrap items-center">
            {row.map((deviceId, colIndex) => {
              const device = deviceById.get(deviceId)
              const [w, h] = device ? orientedDimsCm(device, profileById) : [0, 0]
              return (
                <div
                  key={deviceId}
                  className="row items-center gap-1"
                  style={{ border: '1px solid var(--ink-border)', borderRadius: 8, padding: '4px 8px' }}
                >
                  <Button flat round icon="chevron_left" title="Move left" disabled={colIndex === 0} onClick={() => moveDevice(rowIndex, colIndex, -1)} />
                  <div className="col gap-0">
                    <span className="ink-body">{device?.device_id ?? deviceId.slice(0, 8)}</span>
                    <span className="ink-small">
                      {w.toFixed(1)} x {h.toFixed(1)} cm · {device?.display_orientation}
                    </span>
                  </div>
                  <Button
                    flat
                    round
                    icon="chevron_right"
                    title="Move right"
                    disabled={colIndex === row.length - 1}
                    onClick={() => moveDevice(rowIndex, colIndex, 1)}
                  />
                  <Button flat danger round icon="close" title="Remove" onClick={() => removeDevice(rowIndex, colIndex)} />
                </div>
              )
            })}
            <SelectField
              label=""
              value=""
              onChange={(id) => addDevice(rowIndex, id)}
              options={[
                { value: '', label: available.length ? 'Add device…' : 'No free devices' },
                ...available.map((d) => ({ value: d.id, label: `${d.device_id}${d.room ? ` (${d.room})` : ''}` })),
              ]}
            />
          </div>
        </div>
      ))}
      <Button flat icon="add" disabled={available.length === 0} onClick={() => onChange([...rows, []])}>
        Add row
      </Button>
      <LayoutPreview rows={rows} deviceById={deviceById} profileById={profileById} />
    </div>
  )
}

// Miniature of the resulting wall, using the same flush-tiles assumption as
// the server: no gaps, rows centred, panels centred within their row.
function LayoutPreview({
  rows,
  deviceById,
  profileById,
}: {
  rows: LayoutRows
  deviceById: Map<string, Device>
  profileById: Map<string, DeviceProfile>
}) {
  const sized = rows
    .map((row) =>
      row
        .map((id) => {
          const device = deviceById.get(id)
          if (!device) return null
          const [w, h] = orientedDimsCm(device, profileById)
          return { id, label: device.device_id, w, h }
        })
        .filter((d): d is { id: string; label: string; w: number; h: number } => d != null && d.w > 0),
    )
    .filter((row) => row.length > 0)
  if (sized.length === 0) return null

  const canvasW = Math.max(...sized.map((row) => row.reduce((sum, d) => sum + d.w, 0)))
  const canvasH = sized.reduce((sum, row) => sum + Math.max(...row.map((d) => d.h)), 0)
  const scale = 320 / canvasW

  return (
    <div className="col gap-1">
      <span className="ink-eyebrow">Preview</span>
      <div
        className="col"
        style={{
          width: canvasW * scale,
          height: canvasH * scale,
          border: '1px dashed var(--ink-border)',
          alignItems: 'center',
        }}
      >
        {sized.map((row, i) => {
          const rowH = Math.max(...row.map((d) => d.h))
          return (
            <div key={i} className="row" style={{ height: rowH * scale, alignItems: 'center' }}>
              {row.map((d) => (
                <div
                  key={d.id}
                  title={d.label}
                  style={{
                    width: d.w * scale,
                    height: d.h * scale,
                    border: '1px solid var(--ink-border)',
                    background: 'var(--ink-surface)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 10,
                    overflow: 'hidden',
                  }}
                >
                  {d.label}
                </div>
              ))}
            </div>
          )
        })}
      </div>
      <span className="ink-small">
        Canvas {canvasW.toFixed(1)} x {canvasH.toFixed(1)} cm — computed from panel dimensions, assuming panels sit flush.
      </span>
    </div>
  )
}
