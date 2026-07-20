// Compact proportional rendering of a grid's panel placements, shown
// wherever the user targets a grid (job slot mapping, group creation) so
// they can see where the content is going to be displayed.

import type { Grid } from '../lib/types'

export function GridMiniPreview({
  grid,
  labels,
}: {
  grid: Grid
  // Optional label per slot key "row:col" (e.g. the assigned content part).
  labels?: Record<string, string>
}) {
  const placements = grid.devices ?? []
  if (placements.length === 0) return null
  return (
    <div className="col gap-1" style={{ width: '100%', maxWidth: 380 }}>
      <span className="ink-eyebrow">Where it shows</span>
      <div
        style={{
          width: '100%',
          aspectRatio: `${grid.width_cm} / ${grid.height_cm}`,
          position: 'relative',
          border: '1px dashed var(--ink-border)',
          borderRadius: 8,
        }}
      >
        {placements.map((placement) => {
          const left = (placement.bottom_left_x_cm / grid.width_cm) * 100
          const top = ((grid.height_cm - placement.bottom_left_y_cm - placement.height_cm) / grid.height_cm) * 100
          const label = labels?.[`${placement.row}:${placement.col}`]
          return (
            <div
              key={placement.device_id}
              style={{
                position: 'absolute',
                left: `${left}%`,
                top: `${top}%`,
                width: `${(placement.width_cm / grid.width_cm) * 100}%`,
                height: `${(placement.height_cm / grid.height_cm) * 100}%`,
                border: '1px solid var(--ink-border)',
                background: 'var(--ink-surface)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 11,
                textAlign: 'center',
                overflow: 'hidden',
                padding: 2,
              }}
            >
              {label ?? ''}
            </div>
          )
        })}
      </div>
      <span className="ink-small">
        {grid.name} · {grid.width_cm.toFixed(1)} x {grid.height_cm.toFixed(1)} cm · {placements.length} panel(s)
      </span>
    </div>
  )
}
