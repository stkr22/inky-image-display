// Display-job editor: configure the generated content (prompt, source mode,
// image style), the generation cadence, and which grid slot shows which
// content part; browse/redisplay the stories of the last seven days. The
// display schedule (when a grid shows the generated content) lives on the
// grid page — jobs only generate.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, NumberField, SelectField, Switch, TextArea, TextField } from '../components/fields'
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
  type MotdMessage,
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
      <JobMessages job={job} />
    </div>
  )
}

// --- Actions -------------------------------------------------------------------

function JobActions({ job }: { job: DisplayJob }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['display-job-messages', job.id] })
    queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
    queryClient.invalidateQueries({ queryKey: ['grid-display-status'] })
  }

  const generate = async () => {
    setBusy(true)
    try {
      await api.displayJobGenerate(job.id)
      notify('Generation started — watch its progress in the story list below.', 'positive')
      refresh()
    } catch (err) {
      notify(`Generation failed: ${errMessage(err)}`, 'negative')
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
      notify(`Session started — ${notes.join('; ') || 'no panels pushed'}.`, 'positive')
      refresh()
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bento-tile w-full" style={{ padding: 20 }}>
      <div className="row w-full items-center gap-3 wrap">
        <span className="ink-small">
          {job.last_run_at ? `Last generated ${formatRelative(job.last_run_at)}` : 'Nothing generated yet'}
          {job.interval_minutes != null && job.next_run_at ? ` · next run ${formatRelative(job.next_run_at)}` : ''}
        </span>
        <div className="flex-1" />
        <Button onClick={generate} disabled={busy}>
          Generate now
        </Button>
        <Button primary onClick={display} disabled={busy || !job.target_grid_id}>
          Display now
        </Button>
      </div>
      <span className="ink-small" style={{ opacity: 0.7 }}>
        Sessions (status, duration, release) are controlled on the target grid's page.
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
  const [intervalMinutes, setIntervalMinutes] = useState<number | ''>(job.interval_minutes ?? '')
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
      const interval = Number(intervalMinutes) || 0
      await api.updateDisplayJob(job.id, {
        name: name.trim() || job.name,
        content_prompt: prompt.trim(),
        source_mode: sourceMode,
        image_preset_id: presetId || null,
        clear_image_preset: !presetId,
        target_grid_id: gridId || null,
        clear_target_grid: !gridId,
        interval_minutes: interval > 0 ? interval : null,
        clear_interval: interval <= 0,
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
          <NumberField
            label="Generate every (minutes, blank = manual only)"
            value={intervalMinutes}
            onChange={setIntervalMinutes}
            min={1}
          />
          <span className="ink-small">
            Generation and display are independent: this job produces content on its own cadence (1440 = daily), and
            each grid decides on its own schedule when to show the latest generated story.
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

// --- Story history (last 7 days) --------------------------------------------------

function JobMessages({ job }: { job: DisplayJob }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: messages } = useQuery({
    queryKey: ['display-job-messages', job.id],
    queryFn: () => api.listDisplayJobMessages(job.id, 10),
    // Poll quickly while a generation is running so the progress row updates.
    refetchInterval: (query) => (query.state.data?.some((m) => m.status === 'generating') ? 3000 : 30_000),
  })
  const { data: status } = useQuery({
    queryKey: ['grid-display-status', job.target_grid_id],
    queryFn: () => api.getGridDisplayStatus(job.target_grid_id!),
    enabled: Boolean(job.target_grid_id),
  })
  const [busy, setBusy] = useState(false)
  // undefined = "no manual choice yet" → the newest story starts expanded.
  const [expandedId, setExpandedId] = useState<string | null | undefined>(undefined)

  const display = async (message: MotdMessage) => {
    setBusy(true)
    try {
      const result = await api.displayJobDisplay(job.id, message.id)
      notify(
        `“${message.headline ?? 'Story'}” started — ${result.displayed.length ? `showing on ${result.displayed.join(', ')}` : 'no panels pushed'}.`,
        'positive',
      )
      queryClient.invalidateQueries({ queryKey: ['grid-display-status'] })
      queryClient.invalidateQueries({ queryKey: ['display-job-messages', job.id] })
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const openId = expandedId === undefined ? messages?.[0]?.id : expandedId

  return (
    <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
      <div className="col gap-0">
        <span className="ink-eyebrow">Stories</span>
        <h3 className="ink-h3">Last 7 days</h3>
      </div>
      <span className="ink-small">
        Generated stories are kept for seven days — click one to preview it, or display it again. “Shown” tells you
        which stories were already on the panels.
      </span>
      {!messages?.length && <EmptyNote>No stories generated yet — use “Generate now” above.</EmptyNote>}
      {(messages ?? []).map((message) => {
        const open = openId === message.id
        const showing = status?.active && status.message_id === message.id
        return (
          <div
            key={message.id}
            className="col w-full gap-2"
            style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 12 }}
          >
            <div
              className="row w-full items-center gap-3 wrap"
              style={{ cursor: 'pointer' }}
              onClick={() => setExpandedId(open ? null : message.id)}
            >
              {message.status === 'generating' && (
                <span className="row items-center gap-2">
                  <div className="ink-spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                  <Badge tone="accent">Generating…</Badge>
                </span>
              )}
              {message.status === 'failed' && <Badge tone="warn">Failed</Badge>}
              <span className="ink-body" style={{ fontWeight: 600 }}>
                {message.headline ?? (message.status === 'generating' ? 'New story on its way…' : 'Untitled story')}
              </span>
              <span className="ink-small">{formatRelative(message.created_at)}</span>
              <div className="flex-1" />
              {showing ? (
                <Badge tone="ok">Showing now</Badge>
              ) : message.displayed_at ? (
                <span className="ink-small">shown {formatRelative(message.displayed_at)}</span>
              ) : (
                message.status === 'ready' && <Badge tone="muted">not shown yet</Badge>
              )}
              {message.status === 'ready' && !showing && (
                <Button
                  flat
                  disabled={busy || !job.target_grid_id}
                  onClick={(event) => {
                    event.stopPropagation()
                    display(message)
                  }}
                >
                  Display
                </Button>
              )}
            </div>
            {open && <MessagePreview message={message} />}
          </div>
        )
      })}
    </div>
  )
}

function MessagePreview({ message }: { message: MotdMessage }) {
  return (
    <div className="col w-full gap-2">
      {message.error && <span className="ink-form-error">{message.error}</span>}
      {(
        [
          ['What?', message.what],
          ['Why?', message.why],
          ['When?', message.when_text],
          ['Takeaway', message.takeaway],
        ] as const
      ).map(
        ([label, text]) =>
          text && (
            <div key={label} className="col gap-0">
              <span className="ink-eyebrow">{label}</span>
              <span className="ink-body">{text}</span>
            </div>
          ),
      )}
      {message.source_url && (
        <span className="ink-small">
          Source:{' '}
          <a href={message.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--ink-accent)' }}>
            {message.source_title ?? message.source_url}
          </a>
        </span>
      )}
      {message.screens.length > 0 && (
        <div className="row gap-3 wrap">
          {message.screens.map((screen) => (
            <div key={screen.id} className="col gap-1" style={{ maxWidth: 220 }}>
              <img
                src={mediaUrl(screen.storage_path, 480)}
                alt={`${screen.part} screen`}
                style={{ width: '100%', borderRadius: 8, border: '1px solid var(--ink-border)' }}
              />
              <span className="ink-small">
                {MOTD_PART_LABELS[screen.part] ?? screen.part} · {screen.width}×{screen.height}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
