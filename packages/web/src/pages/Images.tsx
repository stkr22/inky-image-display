// Image library: searchable, filterable, paginated gallery with an upload FAB
// and a multi-select mode for bulk delete / bulk grid assignment.

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Icon, SelectField, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { EmptyNote, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, type ImageListFilters } from '../lib/api'
import { imageTitle, mediaUrl, type Grid, type Image } from '../lib/types'

const PAGE_SIZE = 30
const SEARCH_DEBOUNCE_MS = 300

export function Images() {
  const navigate = useNavigate()
  const [source, setSource] = useState('')
  const [gridFilter, setGridFilter] = useState('')
  const [orientation, setOrientation] = useState('')
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
    search: search || undefined,
    limit: PAGE_SIZE,
    offset,
  }
  const { data: images, isPending, error } = useQuery({
    queryKey: ['images', filters],
    queryFn: () => api.listImages(filters),
    placeholderData: keepPreviousData,
  })

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
            {images && images.length > 0 ? `Showing ${offset + 1}-${offset + images.length}` : 'No results'}
          </span>
          <button
            className="ink-btn ink-btn-flat ink-btn-icon"
            disabled={(images?.length ?? 0) < PAGE_SIZE}
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
          {images?.length === 0 && <EmptyNote>No images.</EmptyNote>}
          {images?.map((image) => (
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
        <BulkActionBar selectedIds={[...selected]} grids={grids ?? []} onDone={exitSelection} />
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
function BulkActionBar({ selectedIds, grids, onDone }: { selectedIds: string[]; grids: Grid[]; onDone: () => void }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [gridDialog, setGridDialog] = useState(false)
  const [targetGrid, setTargetGrid] = useState('')
  const [busy, setBusy] = useState(false)

  const finish = (succeeded: number, failed: number, verb: string) => {
    queryClient.invalidateQueries({ queryKey: ['images'] })
    if (failed === 0) notify(`${succeeded} image(s) ${verb}`, 'positive')
    else notify(`${succeeded} ${verb}, ${failed} failed`, 'warning')
    onDone()
  }

  const bulkDelete = async () => {
    setConfirmDelete(false)
    setBusy(true)
    const results = await Promise.allSettled(selectedIds.map((id) => api.deleteImage(id)))
    const failed = results.filter((r) => r.status === 'rejected').length
    finish(selectedIds.length - failed, failed, 'deleted')
  }

  const bulkSetGrid = async () => {
    setGridDialog(false)
    setBusy(true)
    const body = { target_grid_id: targetGrid || null }
    const results = await Promise.allSettled(selectedIds.map((id) => api.updateImage(id, body)))
    const failed = results.filter((r) => r.status === 'rejected').length
    finish(selectedIds.length - failed, failed, 'updated')
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
