// Shared by the group dialogs.

import type { Grid } from '../../lib/types'

// Row-major panel order of a grid, used for round-robin auto-assignment.
export function placementSlots(grid: Grid | null): Array<{ row: number; col: number }> {
  return (grid?.devices ?? [])
    .map((placement) => ({ row: placement.row, col: placement.col }))
    .sort((a, b) => a.row - b.row || a.col - b.col)
}
