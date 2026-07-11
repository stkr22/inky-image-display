// Image library: searchable, filterable, paginated gallery with an upload FAB
// and a multi-select mode for bulk delete / bulk grid assignment.

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Icon, SelectField, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { EmptyNote, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, type ImageListFilters } from '../lib/api'
import { imageTitle, mediaUrl, type Grid, type Image } from '../lib/types'

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

  const filters: ImageListFilters = {
    source_name: source || undefined,
    is_portrait: orientation === '' ? undefined : orientation === 'portrait',
    target_grid_id: gridFilter && gridFilter !== '__solo__' ? gridFilter : undefined,
    solo_only: gridFilter === '__solo__' || undefined,
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
  selecting,
  selected,
  onToggle,
}: {
  image: Image
  selecting: boolean
  selected: boolean
  onToggle: () => void
}) {
  const body = (
    <>
      <img src={mediaUrl(image.storage_path, 480)} loading="lazy" alt={imageTitle(image)} />
      <span className="ink-thumb-caption">{imageTitle(image)}</span>
      {image.excluded_from_rotation && <span className="ink-badge muted ink-thumb-flag">Excluded</span>}
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
