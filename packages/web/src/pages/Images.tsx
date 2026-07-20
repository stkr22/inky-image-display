// Image library: searchable, filterable, paginated gallery with an upload FAB
// and a multi-select mode for bulk delete / bulk grid assignment.

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Icon, SelectField, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { GridMiniPreview } from '../components/GridMiniPreview'
import { api, type ImageListFilters } from '../lib/api'
import { formatRelative } from '../lib/format'
import { imageTitle, mediaUrl, type Grid, type GroupMemberAssignment, type Image, type ImageGroup } from '../lib/types'

const PAGE_SIZE = 30
const SEARCH_DEBOUNCE_MS = 300
const UNDO_DELETE_MS = 7000

// "3 failed: Sunset, Beach, +1 more" — naming the failures lets the operator
// find the stragglers instead of hunting through the library.
function failureSummary(titles: string[]): string {
  const shown = titles.slice(0, 3).join(', ')
  const extra = titles.length > 3 ? `, +${titles.length - 3} more` : ''
  return `${titles.length} failed: ${shown}${extra}`
}

export function Images() {
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [source, setSource] = useState('')
  const [gridFilter, setGridFilter] = useState('')
  const [groupFilter, setGroupFilter] = useState('')
  const [orientation, setOrientation] = useState('')
  const [excludedFilter, setExcludedFilter] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [searchInput])

  const { data: grids } = useQuery({ queryKey: ['grids'], queryFn: () => api.listGrids() })
  const { data: groups } = useQuery({ queryKey: ['image-groups'], queryFn: () => api.listImageGroups() })

  const filters: ImageListFilters = {
    source_name: source || undefined,
    is_portrait: orientation === '' ? undefined : orientation === 'portrait',
    target_grid_id: gridFilter && gridFilter !== '__solo__' ? gridFilter : undefined,
    solo_only: gridFilter === '__solo__' || undefined,
    group_id: groupFilter && !groupFilter.startsWith('__') ? groupFilter : undefined,
    in_group: groupFilter === '__grouped__' ? true : groupFilter === '__ungrouped__' ? false : undefined,
    excluded: excludedFilter === '' ? undefined : excludedFilter === 'excluded',
    search: search || undefined,
    limit: PAGE_SIZE,
    offset,
  }
  const { data, isPending, error } = useQuery({
    queryKey: ['images', filters],
    queryFn: () => api.listImages(filters),
    placeholderData: keepPreviousData,
  })
  const images = data?.items
  const total = data?.total ?? 0

  // Titles of every image seen so far, so bulk-failure toasts can name items
  // even when the selection spans pages no longer loaded.
  const titlesRef = useRef(new Map<string, string>())
  images?.forEach((img) => titlesRef.current.set(img.id, imageTitle(img)))

  // Deferred bulk delete: selected images are only hidden client-side until
  // the undo window closes, so Undo is a pure no-op (nothing was sent yet).
  const [pendingDeleteIds, setPendingDeleteIds] = useState<ReadonlySet<string>>(new Set())
  const pendingDeleteRef = useRef<{ ids: string[]; timer: ReturnType<typeof setTimeout> } | null>(null)

  const flushPendingDelete = useCallback(async () => {
    const pending = pendingDeleteRef.current
    if (!pending) return
    pendingDeleteRef.current = null
    clearTimeout(pending.timer)
    const results = await Promise.allSettled(pending.ids.map((id) => api.deleteImage(id)))
    const failedIds = pending.ids.filter((_, i) => results[i]?.status === 'rejected')
    if (failedIds.length > 0) {
      const titles = failedIds.map((id) => titlesRef.current.get(id) ?? 'Untitled')
      notify(`${pending.ids.length - failedIds.length} deleted, ${failureSummary(titles)}`, 'warning')
    }
    // Wait for the refetch before un-hiding so successfully deleted images
    // don't flash back into the grid; failures then reappear naturally.
    await queryClient.invalidateQueries({ queryKey: ['images'] })
    setPendingDeleteIds((current) => {
      const next = new Set(current)
      for (const id of pending.ids) next.delete(id)
      return next
    })
  }, [notify, queryClient])

  // Flush on unmount: if the user navigates away mid-undo-window, commit the
  // deletion immediately rather than silently dropping it.
  useEffect(() => {
    return () => {
      void flushPendingDelete()
    }
  }, [flushPendingDelete])

  const scheduleBulkDelete = (ids: string[]) => {
    // One undo window at a time: commit any prior batch before starting a new one.
    void flushPendingDelete()
    const batch = { ids, timer: setTimeout(() => void flushPendingDelete(), UNDO_DELETE_MS) }
    pendingDeleteRef.current = batch
    setPendingDeleteIds((current) => new Set([...current, ...ids]))
    notify(`${ids.length} image(s) deleted`, 'info', {
      durationMs: UNDO_DELETE_MS,
      action: {
        label: 'Undo',
        onClick: () => {
          // A stale toast must not cancel a newer batch.
          if (pendingDeleteRef.current !== batch) return
          clearTimeout(batch.timer)
          pendingDeleteRef.current = null
          setPendingDeleteIds((current) => {
            const next = new Set(current)
            for (const id of batch.ids) next.delete(id)
            return next
          })
        },
      },
    })
  }

  const visibleImages = images?.filter((img) => !pendingDeleteIds.has(img.id))

  const resetAnd = (apply: () => void) => {
    setOffset(0)
    apply()
  }

  const toggleSelected = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const exitSelection = () => {
    setSelecting(false)
    setSelected(new Set())
  }

  const gridOptions = [
    { value: '', label: 'All' },
    { value: '__solo__', label: 'Solo (no grid)' },
    ...(grids ?? []).map((g) => ({ value: g.id, label: `Grid: ${g.name}` })),
  ]

  const groupOptions = [
    { value: '', label: 'All' },
    { value: '__grouped__', label: 'In a group' },
    { value: '__ungrouped__', label: 'Not grouped' },
    ...(groups ?? []).map((g) => ({ value: g.id, label: `Group: ${g.name}` })),
  ]
  const groupNameById = new Map((groups ?? []).map((g) => [g.id, g.name]))

  return (
    <>
      <PageHeader
        eyebrow="Library"
        title="Images"
        actions={
          selecting ? (
            <Button flat onClick={exitSelection}>
              Done
            </Button>
          ) : (
            <Button ghost icon="checklist" onClick={() => setSelecting(true)}>
              Select
            </Button>
          )
        }
      />

      <div className="row w-full items-end gap-3 wrap">
        <TextField label="Search" placeholder="Title, description, tags…" value={searchInput} onChange={setSearchInput} />
        <SelectField
          label="Source"
          value={source}
          onChange={(v) => resetAnd(() => setSource(v))}
          options={[
            { value: '', label: 'All' },
            { value: 'manual', label: 'manual' },
            { value: 'immich', label: 'immich' },
            { value: 'gemini', label: 'gemini' },
          ]}
        />
        <SelectField label="Grid" value={gridFilter} onChange={(v) => resetAnd(() => setGridFilter(v))} options={gridOptions} />
        <SelectField label="Group" value={groupFilter} onChange={(v) => resetAnd(() => setGroupFilter(v))} options={groupOptions} />
        <SelectField
          label="Orientation"
          value={orientation}
          onChange={(v) => resetAnd(() => setOrientation(v))}
          options={[
            { value: '', label: 'All' },
            { value: 'landscape', label: 'Landscape only' },
            { value: 'portrait', label: 'Portrait only' },
          ]}
        />
        <SelectField
          label="Rotation"
          value={excludedFilter}
          onChange={(v) => resetAnd(() => setExcludedFilter(v))}
          options={[
            { value: '', label: 'All' },
            { value: 'in', label: 'In rotation' },
            { value: 'excluded', label: 'Excluded' },
          ]}
        />
        <div className="flex-1" />
        <div className="row gap-1 items-center">
          <button
            className="ink-btn ink-btn-flat ink-btn-icon"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            aria-label="Previous page"
          >
            <Icon name="chevron_left" />
          </button>
          <span className="ink-small">
            {images && images.length > 0 ? `Showing ${offset + 1}–${offset + images.length} of ${total}` : 'No results'}
          </span>
          <button
            className="ink-btn ink-btn-flat ink-btn-icon"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            aria-label="Next page"
          >
            <Icon name="chevron_right" />
          </button>
        </div>
      </div>

      <GroupsSection
        groups={groups ?? []}
        grids={grids ?? []}
        onChanged={() => {
          queryClient.invalidateQueries({ queryKey: ['image-groups'] })
          queryClient.invalidateQueries({ queryKey: ['images'] })
        }}
      />

      {error && <ErrorNote>Failed to load images: {String(error)}</ErrorNote>}
      {isPending ? (
        <Spinner />
      ) : (
        <div
          className="w-full gap-4"
          style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}
        >
          {visibleImages?.length === 0 && <EmptyNote>No images.</EmptyNote>}
          {visibleImages?.map((image) => (
            <GalleryTile
              key={image.id}
              image={image}
              groupName={image.group_id ? (groupNameById.get(image.group_id) ?? 'Group') : null}
              selecting={selecting}
              selected={selected.has(image.id)}
              onToggle={() => toggleSelected(image.id)}
            />
          ))}
        </div>
      )}

      {selecting && selected.size > 0 && (
        <BulkActionBar
          selectedIds={[...selected]}
          grids={grids ?? []}
          onDone={exitSelection}
          onScheduleDelete={scheduleBulkDelete}
          titleFor={(id) => titlesRef.current.get(id) ?? 'Untitled'}
        />
      )}

      {!selecting && (
        <button className="ink-fab" title="Upload image" onClick={() => navigate('/images/new')}>
          <Icon name="upload" style={{ fontSize: 24 }} />
        </button>
      )}
    </>
  )
}

function GalleryTile({
  image,
  groupName,
  selecting,
  selected,
  onToggle,
}: {
  image: Image
  groupName: string | null
  selecting: boolean
  selected: boolean
  onToggle: () => void
}) {
  const body = (
    <>
      <img src={mediaUrl(image.storage_path, 480)} loading="lazy" alt={imageTitle(image)} />
      <span className="ink-thumb-caption">{imageTitle(image)}</span>
      {groupName ? (
        // Grouped images are out of regular rotation — the group's grid
        // queue shows them instead; say so instead of a bare "Excluded".
        <span className="ink-badge muted ink-thumb-flag" title="Shown via its group's grid queue">
          {groupName}
        </span>
      ) : (
        image.excluded_from_rotation && <span className="ink-badge muted ink-thumb-flag">Excluded</span>
      )}
      {selecting && (
        <span
          className="material-icons"
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            borderRadius: 999,
            background: selected ? 'var(--ink-accent)' : 'rgba(255,255,255,0.85)',
            color: selected ? 'white' : 'var(--ink-muted)',
            padding: 2,
            fontSize: 18,
          }}
        >
          {selected ? 'check' : 'radio_button_unchecked'}
        </span>
      )}
    </>
  )
  if (selecting) {
    return (
      <div
        className="ink-thumb"
        style={{ position: 'relative', outline: selected ? '2px solid var(--ink-accent)' : 'none' }}
        onClick={onToggle}
      >
        {body}
      </div>
    )
  }
  return (
    <Link to={`/images/${image.id}`} className="ink-thumb" style={{ position: 'relative' }}>
      {body}
    </Link>
  )
}

// Sticky toolbar shown while a selection exists: bulk delete and bulk
// grid-target assignment (each image is updated/deleted individually; the
// API has no batch endpoint, but N requests is fine at this scale).
function BulkActionBar({
  selectedIds,
  grids,
  onDone,
  onScheduleDelete,
  titleFor,
}: {
  selectedIds: string[]
  grids: Grid[]
  onDone: () => void
  onScheduleDelete: (ids: string[]) => void
  titleFor: (id: string) => string
}) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [gridDialog, setGridDialog] = useState(false)
  const [groupDialog, setGroupDialog] = useState(false)
  const [targetGrid, setTargetGrid] = useState('')
  const [busy, setBusy] = useState(false)

  // Deletion is deferred to the parent (undo window); nothing is sent here.
  const bulkDelete = () => {
    setConfirmDelete(false)
    onScheduleDelete(selectedIds)
    onDone()
  }

  const bulkSetGrid = async () => {
    setGridDialog(false)
    setBusy(true)
    const body = { target_grid_id: targetGrid || null }
    const results = await Promise.allSettled(selectedIds.map((id) => api.updateImage(id, body)))
    const failedIds = selectedIds.filter((_, i) => results[i]?.status === 'rejected')
    queryClient.invalidateQueries({ queryKey: ['images'] })
    if (failedIds.length === 0) notify(`${selectedIds.length} image(s) updated`, 'positive')
    else notify(`${selectedIds.length - failedIds.length} updated, ${failureSummary(failedIds.map(titleFor))}`, 'warning')
    onDone()
  }

  return (
    <div className="ink-action-bar" style={{ position: 'sticky', bottom: 16, zIndex: 20 }}>
      <span className="ink-small" style={{ marginRight: 'auto' }}>
        {selectedIds.length} selected
      </span>
      <Button ghost icon="grid_view" disabled={busy} onClick={() => setGridDialog(true)}>
        Set grid…
      </Button>
      <Button ghost icon="collections" disabled={busy} onClick={() => setGroupDialog(true)}>
        Group…
      </Button>
      <Button flat danger icon="delete" disabled={busy} onClick={() => setConfirmDelete(true)}>
        Delete
      </Button>

      <ConfirmDialog
        open={confirmDelete}
        message={`Delete ${selectedIds.length} image(s)? This also removes the stored files.`}
        destructive
        confirmLabel="Delete all"
        onConfirm={bulkDelete}
        onCancel={() => setConfirmDelete(false)}
      />
      {groupDialog && (
        <CreateGroupDialog
          selectedIds={selectedIds}
          onClose={() => setGroupDialog(false)}
          onCreated={() => {
            setGroupDialog(false)
            queryClient.invalidateQueries({ queryKey: ['images'] })
            queryClient.invalidateQueries({ queryKey: ['image-groups'] })
            onDone()
          }}
        />
      )}
      <Dialog open={gridDialog} onClose={() => setGridDialog(false)}>
        <h3 className="ink-h3">Set target grid</h3>
        <span className="ink-small">Applies to {selectedIds.length} image(s). "(solo rotation)" clears the assignment.</span>
        <SelectField
          label="Target grid"
          value={targetGrid}
          onChange={setTargetGrid}
          options={[
            { value: '', label: '(solo rotation)' },
            ...grids.map((g) => ({ value: g.id, label: g.name })),
          ]}
        />
        <div className="row w-full justify-end gap-2">
          <Button flat onClick={() => setGridDialog(false)}>
            Cancel
          </Button>
          <Button primary onClick={bulkSetGrid}>
            Apply
          </Button>
        </div>
      </Dialog>
    </div>
  )
}

// Row-major panel order of a grid, used for round-robin auto-assignment.
function placementSlots(grid: Grid | null): Array<{ row: number; col: number }> {
  return (grid?.devices ?? [])
    .map((placement) => ({ row: placement.row, col: placement.col }))
    .sort((a, b) => a.row - b.row || a.col - b.col)
}

// Bundle the selected images into a panel spread for a grid: each image
// gets a panel round-robin (extra images stack per panel and rotate).
// Fine-tuning happens in the Groups overview afterwards.
function CreateGroupDialog({
  selectedIds,
  onClose,
  onCreated,
}: {
  selectedIds: string[]
  onClose: () => void
  onCreated: () => void
}) {
  const notify = useNotify()
  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })
  const [name, setName] = useState('')
  const [gridId, setGridId] = useState('')
  const [busy, setBusy] = useState(false)
  // '' = create a new group; otherwise the id of an existing group to extend.
  const [existingId, setExistingId] = useState('')
  const { data: groups } = useQuery({ queryKey: ['image-groups'], queryFn: () => api.listImageGroups() })
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
      notify(`Save failed: ${err instanceof Error ? err.message : String(err)}`, 'negative')
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

// The one place listing every group: worker-generated ones are read-only
// (delete only — their job re-creates them), curated ones are fully
// editable spreads (rename, grid, panel assignments).
function GroupsSection({
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
      notify(`Delete failed: ${err instanceof Error ? err.message : String(err)}`, 'negative')
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
  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })
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
      notify(`Save failed: ${err instanceof Error ? err.message : String(err)}`, 'negative')
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
