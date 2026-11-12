import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errMessage } from '../../lib/api'
import { formatRelative } from '../../lib/format'
import { gridsQuery } from '../../lib/queries'
import { imageTitle, mediaUrl, type Grid, type ImageGroup } from '../../lib/types'
import { ConfirmDialog, Dialog } from '../Dialog'
import { Button, SelectField, TextField } from '../fields'
import { GridMiniPreview } from '../GridMiniPreview'
import { useNotify } from '../Toast'
import { Badge, EmptyNote } from '../ui'
import { placementSlots } from './slots'

// The one place listing every group: worker-generated ones are read-only
// (delete only — their job re-creates them), curated ones are fully
// editable spreads (rename, grid, panel assignments).
export function GroupsSection({
  groups,
  grids,
  onChanged,
}: {
  groups: ImageGroup[]
  grids: Grid[]
  onChanged: () => void
}) {
  const notify = useNotify()
  const [editing, setEditing] = useState<ImageGroup | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<ImageGroup | null>(null)
  const gridNameById = new Map(grids.map((g) => [g.id, g.name]))

  const remove = async (group: ImageGroup) => {
    setConfirmDelete(null)
    const deleteImages = Boolean(group.display_job_id)
    try {
      await api.deleteImageGroup(group.id, deleteImages)
      notify(deleteImages ? 'Group and its screens deleted.' : 'Group dissolved — images stay in the library.', 'positive')
      onChanged()
    } catch (err) {
      notify(`Delete failed: ${errMessage(err)}`, 'negative')
    }
  }

  if (groups.length === 0) return null
  return (
    <div className="ink-card w-full" style={{ gap: 10 }}>
      <h3 className="ink-h3">Groups</h3>
      <span className="ink-small">
        A group shows one coordinated spread: each image covers one panel of its grid. Create groups by selecting
        images below → Group…
      </span>
      {groups.map((group) => (
        <div
          key={group.id}
          className="row w-full items-center gap-2 wrap"
          style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 8 }}
        >
          {group.images[0] && (
            <img
              src={mediaUrl(group.images[0].storage_path, 240)}
              alt=""
              style={{ width: 56, height: 42, objectFit: 'cover', borderRadius: 6 }}
            />
          )}
          <div className="col gap-0" style={{ flex: '1 1 auto', minWidth: 160 }}>
            <span className="ink-body truncate">
              {group.name} {group.display_job_id && <Badge tone="accent">generated</Badge>}
            </span>
            <span className="ink-small">
              {group.target_grid_id ? (gridNameById.get(group.target_grid_id) ?? 'Grid') : 'No grid'} ·{' '}
              {group.images.length} image(s) ·{' '}
              {group.last_displayed_at ? `shown ${formatRelative(group.last_displayed_at)}` : 'not shown yet'}
            </span>
          </div>
          {!group.display_job_id && (
            <Button flat icon="edit" onClick={() => setEditing(group)}>
              Edit
            </Button>
          )}
          <Button flat danger round icon="delete" title="Delete group" onClick={() => setConfirmDelete(group)} />
        </div>
      ))}
      {editing && (
        <EditGroupDialog
          group={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            onChanged()
          }}
        />
      )}
      <ConfirmDialog
        open={confirmDelete !== null}
        message={
          confirmDelete?.display_job_id
            ? `Delete generated group '${confirmDelete.name}' and its screens?`
            : `Dissolve group '${confirmDelete?.name}'? Its images return to the library (they are not deleted).`
        }
        destructive
        confirmLabel={confirmDelete?.display_job_id ? 'Delete' : 'Dissolve'}
        onConfirm={() => confirmDelete && remove(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  )
}

// Full editing for a curated spread: rename, pick the grid, and give each
// image a panel. Several images on one panel rotate there, one per grid
// refresh, in list order.
function EditGroupDialog({ group, onClose, onSaved }: { group: ImageGroup; onClose: () => void; onSaved: () => void }) {
  const notify = useNotify()
  const { data: grids } = useQuery(gridsQuery)
  const [name, setName] = useState(group.name)
  const [gridId, setGridId] = useState(group.target_grid_id ?? '')
  const [members, setMembers] = useState(
    group.images.map((img) => ({ image: img, row: img.group_slot_row, col: img.group_slot_col })),
  )
  const [busy, setBusy] = useState(false)
  const grid = (grids ?? []).find((g) => g.id === gridId) ?? null
  const slots = placementSlots(grid)

  const setSlot = (index: number, key: string) => {
    setMembers((current) =>
      current.map((member, i) => {
        if (i !== index) return member
        if (!key) return { ...member, row: null, col: null }
        const [row, col] = key.split(':').map(Number)
        return { ...member, row, col }
      }),
    )
  }

  // Panel preview labels: first title per panel plus how many more rotate there.
  const bySlot: Record<string, string[]> = {}
  for (const member of members.filter((m) => m.row != null && m.col != null)) {
    ;(bySlot[`${member.row}:${member.col}`] ??= []).push(imageTitle(member.image))
  }
  const labels = Object.fromEntries(
    Object.entries(bySlot).map(([key, titles]) => [key, titles.length > 1 ? `${titles[0]} +${titles.length - 1}` : titles[0]]),
  )

  const save = async () => {
    setBusy(true)
    try {
      await api.updateImageGroup(group.id, {
        name: name.trim() || group.name,
        target_grid_id: gridId || null,
        clear_target_grid: !gridId,
        members: members.map((member) => ({ image_id: member.image.id, row: member.row, col: member.col })),
      })
      notify('Group saved.', 'positive')
      onSaved()
    } catch (err) {
      notify(`Save failed: ${errMessage(err)}`, 'negative')
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Edit group</h3>
      <TextField label="Name" value={name} onChange={setName} />
      <SelectField
        label="Show on grid"
        value={gridId}
        onChange={setGridId}
        options={[{ value: '', label: 'No grid (inactive)' }, ...(grids ?? []).map((g) => ({ value: g.id, label: g.name }))]}
      />
      <span className="ink-small">
        Several images on the same panel rotate there, one per refresh, in list order; images without a panel are not
        shown.
      </span>
      {members.length === 0 && <EmptyNote>No images left — saving dissolves the membership.</EmptyNote>}
      {members.map((member, index) => (
        <div key={member.image.id} className="row w-full items-center gap-2">
          <img
            src={mediaUrl(member.image.storage_path, 240)}
            alt=""
            style={{ width: 56, height: 42, objectFit: 'cover', borderRadius: 6 }}
          />
          <span className="ink-small truncate" style={{ flex: '1 1 auto', minWidth: 120 }}>
            {imageTitle(member.image)}
          </span>
          <SelectField
            label="Panel"
            value={member.row != null && member.col != null ? `${member.row}:${member.col}` : ''}
            onChange={(v) => setSlot(index, v)}
            disabled={!grid}
            options={[
              { value: '', label: 'Not shown' },
              ...slots.map((slot) => ({ value: `${slot.row}:${slot.col}`, label: `Row ${slot.row + 1} · Pos ${slot.col + 1}` })),
            ]}
          />
          <Button
            flat
            danger
            round
            icon="close"
            title="Remove from group (stays in the library)"
            onClick={() => setMembers((current) => current.filter((_, i) => i !== index))}
          />
        </div>
      ))}
      {grid && <GridMiniPreview grid={grid} labels={labels} />}
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={save} disabled={busy}>
          Save
        </Button>
      </div>
    </Dialog>
  )
}
