import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errMessage } from '../../lib/api'
import { gridsQuery, imageGroupsQuery } from '../../lib/queries'
import type { GroupMemberAssignment } from '../../lib/types'
import { Dialog } from '../Dialog'
import { Button, SelectField, TextField } from '../fields'
import { GridMiniPreview } from '../GridMiniPreview'
import { useNotify } from '../Toast'
import { placementSlots } from './slots'

// Bundle the selected images into a panel spread for a grid: each image
// gets a panel round-robin (extra images stack per panel and rotate).
// Fine-tuning happens in the Groups overview afterwards.
export function CreateGroupDialog({
  selectedIds,
  onClose,
  onCreated,
}: {
  selectedIds: string[]
  onClose: () => void
  onCreated: () => void
}) {
  const notify = useNotify()
  const { data: grids } = useQuery(gridsQuery)
  const [name, setName] = useState('')
  const [gridId, setGridId] = useState('')
  const [busy, setBusy] = useState(false)
  // '' = create a new group; otherwise the id of an existing group to extend.
  const [existingId, setExistingId] = useState('')
  const { data: groups } = useQuery(imageGroupsQuery)
  // Generated groups are read-only worker output — only curated groups
  // are offered as an add target.
  const curated = (groups ?? []).filter((g) => g.display_job_id === null)
  const existing = curated.find((g) => g.id === existingId) ?? null
  const grid = (grids ?? []).find((g) => g.id === (existing ? existing.target_grid_id : gridId)) ?? null
  const slots = placementSlots(grid)
  const slotAt = (index: number) => (slots.length > 0 ? slots[index % slots.length] : null)

  // Existing members keep their panels; appended images continue the
  // round-robin where the member count left off.
  const kept: GroupMemberAssignment[] = (existing?.images ?? []).map((img) => ({
    image_id: img.id,
    row: img.group_slot_row,
    col: img.group_slot_col,
  }))
  const added = selectedIds.filter((id) => !existing?.images.some((img) => img.id === id))
  const members = [
    ...kept,
    ...added.map((id, index) => {
      const slot = slotAt(kept.length + index)
      return { image_id: id, row: slot?.row ?? null, col: slot?.col ?? null }
    }),
  ]

  const counts: Record<string, number> = {}
  for (const member of members.filter((m) => m.row != null && m.col != null)) {
    const key = `${member.row}:${member.col}`
    counts[key] = (counts[key] ?? 0) + 1
  }
  const previewLabels = Object.fromEntries(
    Object.entries(counts).map(([key, count]) => [key, count > 1 ? `${count} images` : '1 image']),
  )

  const submit = async () => {
    setBusy(true)
    try {
      if (existing) {
        await api.updateImageGroup(existing.id, { members })
        notify(`${added.length} image(s) added to '${existing.name}'.`, 'positive')
      } else {
        await api.createImageGroup({ name: name.trim(), target_grid_id: gridId || null, members })
        notify(`Group '${name.trim()}' created with ${selectedIds.length} image(s).`, 'positive')
      }
      onCreated()
    } catch (err) {
      notify(`Save failed: ${errMessage(err)}`, 'negative')
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Group {selectedIds.length} image(s)</h3>
      <span className="ink-small">
        Each image covers one panel of the grid, assigned in order; fine-tune under Groups on this page.
      </span>
      {curated.length > 0 && (
        <SelectField
          label="Group"
          value={existingId}
          onChange={setExistingId}
          options={[
            { value: '', label: 'New group…' },
            ...curated.map((g) => ({ value: g.id, label: `Add to: ${g.name} (${g.images.length} images)` })),
          ]}
        />
      )}
      {!existing && <TextField label="Group name" value={name} onChange={setName} placeholder="Summer holiday" />}
      {!existing && (
        <SelectField
          label="Show on grid"
          value={gridId}
          onChange={setGridId}
          options={[
            { value: '', label: 'No grid yet (assign panels later)' },
            ...(grids ?? []).map((g) => ({ value: g.id, label: g.name })),
          ]}
        />
      )}
      {grid && <GridMiniPreview grid={grid} labels={previewLabels} />}
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={submit} disabled={busy || (!existing && !name.trim())}>
          {existing ? 'Add to group' : 'Create group'}
        </Button>
      </div>
    </Dialog>
  )
}
