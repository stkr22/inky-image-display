// Display-job editor: configure the generated content (prompt, source mode,
// image style), the generation cadence, and which grid slot shows which
// content part; browse/redisplay the generated groups of the last seven
// days. The display schedule (when a grid shows the generated content)
// lives on the grid page — jobs only generate, and the external worker
// does the generating.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, SelectField, Switch, TextArea, TextField } from '../components/fields'
import { ScheduleEditor, type ScheduleValue } from '../components/ScheduleEditor'
import { GridMiniPreview } from '../components/GridMiniPreview'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, ErrorNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatRelative } from '../lib/format'
import {
  MOTD_COMPOUND_PARTS,
  MOTD_PART_LABELS,
  MOTD_PARTS,
  mediaUrl,
  type DisplayJob,
  type Grid,
  type ImageGroup,
} from '../lib/types'

const PART_CHOICES = [...MOTD_PARTS, ...MOTD_COMPOUND_PARTS]

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

export function DisplayJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  const { data: jobs, isPending } = useQuery({ queryKey: ['display-jobs'], queryFn: api.listDisplayJobs })
  const { data: grids } = useQuery({ queryKey: ['grids', 'with-devices'], queryFn: () => api.listGrids(true) })

  const job = (jobs ?? []).find((entry) => entry.id === jobId) ?? null

  if (isPending) return <Spinner />
  if (!job) return <ErrorNote>Display job not found.</ErrorNote>

  return (
    <div className="col w-full gap-4">
      <PageHeader eyebrow="Display job" title={job.name}>
        <Link to="/jobs?tab=display" className="ink-small">
          ← All jobs
        </Link>
      </PageHeader>
      <JobActions job={job} />
      <JobConfig key={job.updated_at} job={job} grids={grids ?? []} />
      <JobGroups job={job} />
    </div>
  )
}

// --- Actions -------------------------------------------------------------------

function JobActions({ job }: { job: DisplayJob }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['display-job-groups', job.id] })
    queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
    queryClient.invalidateQueries({ queryKey: ['grid-display-status'] })
  }

  const runNow = async () => {
    setBusy(true)
    try {
      await api.runDisplayJobNow(job.id)
      notify('Run queued — the worker picks it up on its next tick.', 'positive')
      refresh()
    } catch (err) {
      notify(`Run request failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const display = async () => {
    setBusy(true)
    try {
      const result = await api.displayJobDisplay(job.id)
      const notes: string[] = []
      if (result.displayed.length) notes.push(`showing on ${result.displayed.join(', ')}`)
      if (result.offline.length) notes.push(`offline: ${result.offline.join(', ')}`)
      if (result.skipped_no_content.length) notes.push(`nothing to show: ${result.skipped_no_content.join(', ')}`)
      notify(`Now showing — ${notes.join('; ') || 'no panels pushed'}.`, 'positive')
      refresh()
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const runQueued = job.run_requested_at != null
  return (
    <div className="bento-tile w-full" style={{ padding: 20 }}>
      <div className="row w-full items-center gap-3 wrap">
        <span className="ink-small">
          {job.last_run_at ? `Last generated ${formatRelative(job.last_run_at)}` : 'Nothing generated yet'}
          {job.schedule_cron != null && job.next_run_at ? ` · next run ${formatRelative(job.next_run_at)}` : ''}
        </span>
        {runQueued && <Badge tone="accent">Run queued</Badge>}
        <div className="flex-1" />
        <Button onClick={runNow} disabled={busy || runQueued || !job.target_grid_id}>
          Run now
        </Button>
        <Button primary onClick={display} disabled={busy || !job.target_grid_id}>
          Display now
        </Button>
      </div>
      <span className="ink-small" style={{ opacity: 0.7 }}>
        Generation runs on the external worker; the display schedule and release live on the target grid's page.
      </span>
    </div>
  )
}

// --- Configuration --------------------------------------------------------------

function JobConfig({ job, grids }: { job: DisplayJob; grids: Grid[] }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: presets } = useQuery({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })

  const [name, setName] = useState(job.name)
  const [prompt, setPrompt] = useState(job.content_prompt)
  const [sourceMode, setSourceMode] = useState<string>(job.source_mode)
  const [presetId, setPresetId] = useState(job.image_preset_id ?? '')
  const [gridId, setGridId] = useState(job.target_grid_id ?? '')
  const [schedule, setSchedule] = useState<ScheduleValue>({ cron: job.schedule_cron, timezone: job.schedule_timezone || 'UTC' })
  // One part per slot (single or a "two texts on one screen" combo).
  const [slotParts, setSlotParts] = useState<Record<string, string>>(() =>
    Object.fromEntries(job.slots.map((slot) => [`${slot.row}:${slot.col}`, slot.parts[0] ?? 'what'])),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const grid = grids.find((g) => g.id === gridId) ?? null
  const deviceById = new Map((devices ?? []).map((d) => [d.id, d]))
  const placements = [...(grid?.devices ?? [])].sort((a, b) => a.row - b.row || a.col - b.col)

  const toggleSlot = (key: string, participating: boolean) => {
    setSlotParts((prev) => {
      const next = { ...prev }
      if (participating) next[key] = next[key] ?? 'what'
      else delete next[key]
      return next
    })
  }

  const save = async () => {
    if (!prompt.trim()) return setError('The content prompt is required')
    setSaving(true)
    setError('')
    try {
      await api.updateDisplayJob(job.id, {
        name: name.trim() || job.name,
        content_prompt: prompt.trim(),
        source_mode: sourceMode,
        image_preset_id: presetId || null,
        clear_image_preset: !presetId,
        target_grid_id: gridId || null,
        clear_target_grid: !gridId,
        schedule_cron: schedule.cron,
        schedule_timezone: schedule.timezone || 'UTC',
        clear_schedule: schedule.cron == null,
        slots: Object.entries(slotParts).map(([key, part]) => {
          const [row, col] = key.split(':').map(Number)
          return { row, col, parts: [part] }
        }),
      })
      notify('Display job saved.', 'positive')
      queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
    } catch (err) {
      setError(`Save failed: ${errMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  // Labels for the mini preview: the part each panel will show.
  const previewLabels = Object.fromEntries(
    placements.map((placement) => {
      const key = `${placement.row}:${placement.col}`
      const part = slotParts[key]
      return [key, part ? (MOTD_PART_LABELS[part] ?? part) : '—']
    }),
  )

  return (
    <div className="col w-full gap-4">
      <div className="row w-full gap-4 wrap items-stretch">
        <div className="bento-tile col gap-3 flex-1" style={{ padding: 20, minWidth: 340 }}>
          <div className="col gap-0">
            <span className="ink-eyebrow">Content</span>
            <h3 className="ink-h3">What kind of story?</h3>
          </div>
          <TextField label="Job name" value={name} onChange={setName} />
          <TextArea
            label="Story themes prompt"
            value={prompt}
            onChange={setPrompt}
            rows={7}
            counter
            maxLength={4000}
          />
          <div className="row gap-2">
            <Button flat onClick={() => setPrompt(job.default_prompt)}>
              Reset to default
            </Button>
          </div>
          <div className="row gap-3 w-full wrap">
            <SelectField
              label="Story source"
              value={sourceMode}
              onChange={setSourceMode}
              className="flex-1"
              options={[
                { value: 'grounded', label: 'Recent news (Google Search grounding, real source links)' },
                { value: 'knowledge', label: 'Timeless stories (model knowledge, no web search)' },
              ]}
            />
            <SelectField
              label="Image style preset"
              value={presetId}
              onChange={setPresetId}
              className="flex-1"
              options={[
                { value: '', label: 'Default preset' },
                ...(presets ?? []).map((preset) => ({ value: preset.id, label: preset.name })),
              ]}
            />
          </div>
          {sourceMode === 'knowledge' && (
            <span className="ink-small">
              Without web search there is no reliable source link, so the QR screen is skipped.
            </span>
          )}
        </div>

        <div className="bento-tile col gap-3 flex-1" style={{ padding: 20, minWidth: 340 }}>
          <div className="col gap-0">
            <span className="ink-eyebrow">Generation</span>
            <h3 className="ink-h3">How often is new content made?</h3>
          </div>
          <ScheduleEditor value={schedule} onChange={setSchedule} />
          <span className="ink-small">
            Generation and display are independent: the worker produces content on this schedule, and each grid
            decides on its own schedule when to show the latest generated group.
          </span>
        </div>
      </div>

      <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
        <div className="col gap-0">
          <span className="ink-eyebrow">Target</span>
          <h3 className="ink-h3">Which grid slot shows which part?</h3>
        </div>
        <SelectField
          label="Target grid"
          value={gridId}
          onChange={(id) => {
            setGridId(id)
            setSlotParts({})
          }}
          options={[
            { value: '', label: 'No grid selected' },
            ...grids.map((g) => ({ value: g.id, label: `${g.name} (${g.devices?.length ?? 0} panels)` })),
          ]}
          help="A single display works too — put it in a one-panel grid first."
        />
        <span className="ink-small">
          Each panel shows one part of the story. Combined parts like “What + Why” put two short texts on one screen.
          Unmapped panels are left alone.
        </span>
        {!grid && <EmptyNote>Pick a target grid to map its panels.</EmptyNote>}
        {grid && placements.length === 0 && <EmptyNote>The selected grid has no panels yet.</EmptyNote>}
        {grid && placements.length > 0 && <GridMiniPreview grid={grid} labels={previewLabels} />}
        {placements.map((placement) => {
          const key = `${placement.row}:${placement.col}`
          const device = deviceById.get(placement.device_id)
          const participating = key in slotParts
          return (
            <div
              key={key}
              className="row w-full items-center gap-3 wrap"
              style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 12 }}
            >
              <Switch
                checked={participating}
                onChange={(v) => toggleSlot(key, v)}
                label={device?.device_id ?? placement.device_id.slice(0, 8)}
              />
              {device && (
                <Badge tone={device.is_online ? 'ok' : 'muted'}>{device.is_online ? 'online' : 'offline'}</Badge>
              )}
              <span className="ink-small">
                Row {placement.row + 1}, position {placement.col + 1}
                {device?.room ? ` · ${device.room}` : ''} · {device?.display_orientation ?? ''}
              </span>
              <div className="flex-1" />
              {participating && (
                <SelectField
                  value={slotParts[key]}
                  onChange={(part) => setSlotParts((prev) => ({ ...prev, [key]: part }))}
                  className="motd-part-select"
                  options={PART_CHOICES.map((part) => ({ value: part, label: MOTD_PART_LABELS[part] }))}
                />
              )}
            </div>
          )
        })}
      </div>

      <div className="row w-full items-center gap-3">
        {error && <span className="ink-form-error">{error}</span>}
        <div className="flex-1" />
        <Button primary onClick={save} disabled={saving}>
          Save configuration
        </Button>
      </div>
    </div>
  )
}

// --- Generated groups (last 7 days) ------------------------------------------------

function JobGroups({ job }: { job: DisplayJob }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: groups } = useQuery({
    queryKey: ['display-job-groups', job.id],
    queryFn: () => api.listDisplayJobGroups(job.id, 10),
    refetchInterval: 30_000,
  })
  const { data: status } = useQuery({
    queryKey: ['grid-display-status', job.target_grid_id],
    queryFn: () => api.getGridDisplayStatus(job.target_grid_id!),
    enabled: Boolean(job.target_grid_id),
  })
  const [busy, setBusy] = useState(false)
  // undefined = "no manual choice yet" → the newest group starts expanded.
  const [expandedId, setExpandedId] = useState<string | null | undefined>(undefined)

  const display = async (group: ImageGroup) => {
    setBusy(true)
    try {
      const result = await api.displayJobDisplay(job.id, group.id)
      notify(
        `“${group.name}” started — ${result.displayed.length ? `showing on ${result.displayed.join(', ')}` : 'no panels pushed'}.`,
        'positive',
      )
      queryClient.invalidateQueries({ queryKey: ['grid-display-status'] })
      queryClient.invalidateQueries({ queryKey: ['display-job-groups', job.id] })
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const openId = expandedId === undefined ? groups?.[0]?.id : expandedId

  return (
    <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
      <div className="col gap-0">
        <span className="ink-eyebrow">Generated groups</span>
        <h3 className="ink-h3">Last 7 days</h3>
      </div>
      <span className="ink-small">
        Each worker run bundles its screens into an image group targeting the grid; groups are kept for seven days.
        Click one to preview it, or display it again.
      </span>
      {!groups?.length && <EmptyNote>Nothing generated yet — use “Run now” above.</EmptyNote>}
      {(groups ?? []).map((group) => {
        const open = openId === group.id
        const showing = status?.group_id === group.id
        return (
          <div
            key={group.id}
            className="col w-full gap-2"
            style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 12 }}
          >
            <div
              className="row w-full items-center gap-3 wrap"
              style={{ cursor: 'pointer' }}
              onClick={() => setExpandedId(open ? null : group.id)}
            >
              <span className="ink-body" style={{ fontWeight: 600 }}>
                {group.name}
              </span>
              <span className="ink-small">{formatRelative(group.created_at)}</span>
              <div className="flex-1" />
              {showing ? (
                <Badge tone="ok">Showing now</Badge>
              ) : group.last_displayed_at ? (
                <span className="ink-small">shown {formatRelative(group.last_displayed_at)}</span>
              ) : (
                <Badge tone="muted">not shown yet</Badge>
              )}
              {!showing && (
                <Button
                  flat
                  disabled={busy || !job.target_grid_id}
                  onClick={(event) => {
                    event.stopPropagation()
                    display(group)
                  }}
                >
                  Display
                </Button>
              )}
            </div>
            {open && <GroupPreview group={group} />}
          </div>
        )
      })}
    </div>
  )
}

function GroupPreview({ group }: { group: ImageGroup }) {
  return (
    <div className="col w-full gap-2">
      {group.description && <span className="ink-body">{group.description}</span>}
      {group.source_url && (
        <span className="ink-small">
          Source:{' '}
          <a href={group.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--ink-accent)' }}>
            {group.source_url}
          </a>
        </span>
      )}
      {group.images.length > 0 && (
        <div className="row gap-3 wrap">
          {group.images.map((image) => (
            <div key={image.id} className="col gap-1" style={{ maxWidth: 220 }}>
              <img
                src={mediaUrl(image.storage_path, 480)}
                alt={image.title ?? 'screen'}
                style={{ width: '100%', borderRadius: 8, border: '1px solid var(--ink-border)' }}
              />
              <span className="ink-small">
                {image.group_slot_row != null
                  ? `Slot ${image.group_slot_row + 1}.${image.group_slot_col! + 1}`
                  : 'Full canvas'}{' '}
                · {image.original_width}×{image.original_height}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
