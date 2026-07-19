// Unified jobs listing — Immich + Gemini + display jobs in one tabbed page.
// The tab lives in the URL (?tab=gemini|display) so deep links and
// back/forward work.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Switch, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatDatetime, formatRelative, humanizeSeconds } from '../lib/format'
import type { DisplayJob, GeminiJob, SyncJob, SyncJobRun } from '../lib/types'

function scheduleSummary(job: Pick<SyncJob, 'interval_minutes' | 'next_run_at'> & { is_active?: boolean }): string {
  if (job.interval_minutes == null) return 'Manual runs only'
  const cadence = `Runs every ${humanizeSeconds(job.interval_minutes * 60)}`
  if (job.is_active === false) return `${cadence} (paused)`
  return job.next_run_at ? `${cadence} · next ${formatRelative(job.next_run_at)}` : cadence
}

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

export function Jobs() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const requested = searchParams.get('tab')
  const tab = requested === 'gemini' || requested === 'display' ? requested : 'immich'
  const [createDisplayOpen, setCreateDisplayOpen] = useState(false)

  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const profileMap = new Map((profiles ?? []).map((p) => [p.id, p.name]))

  const newLabels = { immich: 'New Immich job', gemini: 'New Gemini job', display: 'New display job' } as const

  return (
    <>
      <PageHeader
        eyebrow="Automations"
        title="Jobs"
        actions={
          <Button
            primary
            icon="add"
            onClick={() => {
              if (tab === 'display') setCreateDisplayOpen(true)
              else navigate(tab === 'gemini' ? '/gemini-jobs/new' : '/sync-jobs/new')
            }}
          >
            {newLabels[tab]}
          </Button>
        }
      />

      <div
        className="row w-full gap-2 items-center"
        style={{ borderBottom: '1px solid var(--ink-border)', paddingBottom: 8 }}
      >
        <Button primary={tab === 'immich'} flat={tab !== 'immich'} icon="sync" onClick={() => setSearchParams({})}>
          Immich
        </Button>
        <Button
          primary={tab === 'gemini'}
          flat={tab !== 'gemini'}
          icon="bolt"
          onClick={() => setSearchParams({ tab: 'gemini' })}
        >
          Gemini
        </Button>
        <Button
          primary={tab === 'display'}
          flat={tab !== 'display'}
          icon="wb_sunny"
          onClick={() => setSearchParams({ tab: 'display' })}
        >
          Display
        </Button>
      </div>

      {tab === 'immich' && <ImmichList profileMap={profileMap} />}
      {tab === 'gemini' && <GeminiList profileMap={profileMap} />}
      {tab === 'display' && <DisplayList />}
      {createDisplayOpen && <CreateDisplayJobDialog onClose={() => setCreateDisplayOpen(false)} />}
    </>
  )
}

// Runs per job (newest first), from one bulk fetch — the list is pruned
// server-side to ~20 runs per job, so 200 rows covers every job's history.
function useRunsByJob(jobType: 'immich' | 'gemini'): Map<string, SyncJobRun[]> {
  const { data: runs } = useQuery({
    queryKey: ['sync-runs', jobType],
    queryFn: () => api.listSyncRuns({ job_type: jobType, limit: 200 }),
    // Runs land whenever the worker cron fires; poll on the same cadence
    // as the schedule view so "Run now" feedback appears without a reload.
    refetchInterval: 15_000,
  })
  const byJob = new Map<string, SyncJobRun[]>()
  for (const run of runs ?? []) {
    byJob.set(run.job_id, [...(byJob.get(run.job_id) ?? []), run]) // list is newest-first
  }
  return byJob
}

function ImmichList({ profileMap }: { profileMap: Map<string, string> }) {
  const { data: jobs, isPending } = useQuery({
    queryKey: ['sync-jobs'],
    queryFn: api.listSyncJobs,
    refetchInterval: 15_000,
  })
  const runsByJob = useRunsByJob('immich')
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) return <EmptyNote>No Immich sync jobs yet.</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => (
        <ImmichRow key={job.id} job={job} profileMap={profileMap} runs={runsByJob.get(job.id) ?? []} />
      ))}
    </div>
  )
}

function ImmichRow({
  job,
  profileMap,
  runs,
}: {
  job: SyncJob
  profileMap: Map<string, string>
  runs: SyncJobRun[]
}) {
  const navigate = useNavigate()
  const targetName = profileMap.get(job.target_device_profile_id) ?? job.target_device_profile_id
  return (
    <JobRow
      name={job.name}
      summary={`${job.strategy} · count ${job.count} · → ${targetName} · ${job.orientation || 'any orientation'}`}
      schedule={scheduleSummary(job)}
      updatedAt={job.updated_at}
      isActive={job.is_active}
      runs={runs}
      runRequestedAt={job.run_requested_at}
      queryKey={['sync-jobs']}
      onToggle={(value) => api.updateSyncJob(job.id, { is_active: value })}
      onRunNow={() => api.runSyncJobNow(job.id)}
      onEdit={() => navigate(`/sync-jobs/${job.id}`)}
      onDelete={() => api.deleteSyncJob(job.id)}
      deleteMessage={`Delete sync job '${job.name}'?`}
    />
  )
}

function GeminiList({ profileMap }: { profileMap: Map<string, string> }) {
  const { data: jobs, isPending } = useQuery({
    queryKey: ['gemini-jobs'],
    queryFn: api.listGeminiJobs,
    refetchInterval: 15_000,
  })
  const runsByJob = useRunsByJob('gemini')
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) return <EmptyNote>No Gemini jobs yet.</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => (
        <GeminiRow key={job.id} job={job} profileMap={profileMap} runs={runsByJob.get(job.id) ?? []} />
      ))}
    </div>
  )
}

function GeminiRow({
  job,
  profileMap,
  runs,
}: {
  job: GeminiJob
  profileMap: Map<string, string>
  runs: SyncJobRun[]
}) {
  const navigate = useNavigate()
  const targetName = profileMap.get(job.target_device_profile_id) ?? job.target_device_profile_id
  const total = (job.subjects?.length ?? 0) * (job.images_per_subject || 1)
  return (
    <JobRow
      name={job.name}
      summary={`${job.orientation || 'portrait'} · ${total} images per run · → ${targetName}`}
      schedule={scheduleSummary(job)}
      updatedAt={job.updated_at}
      isActive={job.is_active}
      runs={runs}
      runRequestedAt={job.run_requested_at}
      queryKey={['gemini-jobs']}
      onToggle={(value) => api.updateGeminiJob(job.id, { is_active: value })}
      onRunNow={() => api.runGeminiJobNow(job.id)}
      onEdit={() => navigate(`/gemini-jobs/${job.id}`)}
      onDelete={() => api.deleteGeminiJob(job.id)}
      deleteMessage={`Delete Gemini job '${job.name}'?`}
    />
  )
}

// --- Display jobs (generated grid content) --------------------------------------

function DisplayList() {
  const { data: jobs, isPending } = useQuery({
    queryKey: ['display-jobs'],
    queryFn: api.listDisplayJobs,
    refetchInterval: 15_000,
  })
  const { data: grids } = useQuery({ queryKey: ['grids'], queryFn: () => api.listGrids() })
  const gridName = new Map((grids ?? []).map((g) => [g.id, g.name]))
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) {
    return <EmptyNote>No display jobs yet — create one and point it at a grid.</EmptyNote>
  }
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => (
        <DisplayJobRow key={job.id} job={job} gridName={gridName} />
      ))}
    </div>
  )
}

function DisplayJobRow({ job, gridName }: { job: DisplayJob; gridName: Map<string, string> }) {
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)

  const generateMutation = useMutation({
    mutationFn: () => api.displayJobGenerate(job.id),
    onSuccess: () => {
      notify('Generation started — see the job page for progress', 'positive')
      queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
    },
    onError: (err) => notify(`Generation failed: ${errMessage(err)}`, 'negative'),
  })
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteDisplayJob(job.id),
    onSuccess: () => {
      notify('Deleted', 'positive')
      queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
    },
    onError: (err) => notify(`Delete failed: ${errMessage(err)}`, 'negative'),
  })

  const target = job.target_grid_id
    ? `→ ${gridName.get(job.target_grid_id) ?? 'grid'}`
    : 'no target grid yet'

  return (
    <div className="bento-tile w-full" style={{ padding: '16px 20px', gap: 12 }}>
      <div className="row w-full items-center" style={{ gap: 12 }}>
        <div className="col flex-1 gap-1">
          <div className="row items-center gap-2 wrap">
            <h3 className="ink-h3 truncate">{job.name}</h3>
            {!job.target_grid_id && <Badge tone="warn">No grid</Badge>}
          </div>
          <span className="ink-small">
            {job.job_type} · {target} · {job.slots.length} slot(s) mapped
          </span>
          <span className="ink-small">{scheduleSummary(job)}</span>
          <span className="ink-small">
            {job.last_run_at ? `Last generated ${formatRelative(job.last_run_at)}` : 'Nothing generated yet'}
          </span>
        </div>
        <Button
          flat
          round
          icon="play_arrow"
          title="Generate now"
          disabled={generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
        />
        <Button flat round icon="edit" title="Edit" onClick={() => navigate(`/display-jobs/${job.id}`)} />
        <Button flat danger round icon="delete" title="Delete" onClick={() => setConfirmDelete(true)} />
      </div>
      <ConfirmDialog
        open={confirmDelete}
        message={`Delete display job '${job.name}'? A session showing its content is released first.`}
        destructive
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false)
          deleteMutation.mutate()
        }}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}

function CreateDisplayJobDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [name, setName] = useState('Message of the day')

  const create = async () => {
    try {
      const job = await api.createDisplayJob({ name })
      queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
      notify('Display job created — pick its target grid next.', 'positive')
      navigate(`/display-jobs/${job.id}`)
      onClose()
    } catch (err) {
      notify(`Create failed: ${errMessage(err)}`, 'negative')
    }
  }

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">New display job</h3>
      <TextField label="Name" value={name} onChange={setName} />
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={create} disabled={!name}>
          Create
        </Button>
      </div>
    </Dialog>
  )
}

function lastRunSummary(run: SyncJobRun): string {
  if (run.status === 'error') return run.error || 'failed'
  const parts = [`${run.images_added} added`]
  if (run.images_skipped > 0) parts.push(`${run.images_skipped} skipped`)
  if (run.images_deleted > 0) parts.push(`${run.images_deleted} expired`)
  return parts.join(', ')
}

function JobRow({
  name,
  summary,
  schedule,
  updatedAt,
  isActive,
  runs,
  runRequestedAt,
  queryKey,
  onToggle,
  onRunNow,
  onEdit,
  onDelete,
  deleteMessage,
}: {
  name: string
  summary: string
  schedule: string
  updatedAt: string
  isActive: boolean
  runs: SyncJobRun[]
  runRequestedAt: string | null
  queryKey: string[]
  onToggle: (value: boolean) => Promise<unknown>
  onRunNow: () => Promise<unknown>
  onEdit: () => void
  onDelete: () => Promise<unknown>
  deleteMessage: string
}) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  // Optimistic toggle: flip immediately, roll back on error.
  const [optimisticActive, setOptimisticActive] = useState<boolean | null>(null)
  const shownActive = optimisticActive ?? isActive
  const lastRun = runs[0] ?? null

  const toggleMutation = useMutation({
    mutationFn: onToggle,
    onSuccess: () => {
      notify('Updated', 'positive')
      queryClient.invalidateQueries({ queryKey })
    },
    onError: (err) => {
      setOptimisticActive(null)
      notify(`Toggle failed: ${errMessage(err)}`, 'negative')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: onDelete,
    onSuccess: () => {
      notify('Deleted', 'positive')
      queryClient.invalidateQueries({ queryKey })
    },
    onError: (err) => notify(`Delete failed: ${errMessage(err)}`, 'negative'),
  })

  const runNowMutation = useMutation({
    mutationFn: onRunNow,
    onSuccess: () => {
      notify('Run queued — the worker picks it up on its next tick', 'positive')
      queryClient.invalidateQueries({ queryKey })
    },
    onError: (err) => notify(`Run request failed: ${errMessage(err)}`, 'negative'),
  })
  const runQueued = runRequestedAt != null

  return (
    <div className="bento-tile w-full" style={{ padding: '16px 20px', gap: 12 }}>
      <div className="row w-full items-center" style={{ gap: 12 }}>
        <div className="col flex-1 gap-1">
          <div className="row items-center gap-2 wrap">
            <h3 className="ink-h3 truncate">{name}</h3>
            {runQueued && <Badge tone="accent">Run queued</Badge>}
            {lastRun?.status === 'error' && <Badge tone="danger">Last run failed</Badge>}
          </div>
          <span className="ink-small">{summary}</span>
          <span className="ink-small">{schedule}</span>
        {lastRun ? (
          <span className="ink-small" style={lastRun.status === 'error' ? { color: 'var(--ink-danger)' } : undefined}>
            Last run {formatRelative(lastRun.finished_at)}: {lastRunSummary(lastRun)}
          </span>
        ) : (
          <span className="ink-small" style={{ opacity: 0.7 }}>
            No runs recorded yet
          </span>
        )}
          <span className="ink-small">Updated {formatDatetime(updatedAt)}</span>
        </div>
        <Button
          flat
          round
          icon="history"
          title={historyOpen ? 'Hide run history' : 'Show run history'}
          disabled={runs.length === 0}
          onClick={() => setHistoryOpen((open) => !open)}
        />
        <Button
          flat
          round
          icon="play_arrow"
          title={runQueued ? 'Run already queued' : 'Run now'}
          disabled={runQueued || runNowMutation.isPending}
          onClick={() => runNowMutation.mutate()}
        />
        <Switch
          checked={shownActive}
          onChange={(value) => {
            setOptimisticActive(value)
            toggleMutation.mutate(value)
          }}
        />
        <Button flat round icon="edit" title="Edit" onClick={onEdit} />
        <Button flat danger round icon="delete" title="Delete" onClick={() => setConfirmDelete(true)} />
      </div>
      {historyOpen && (
        <div className="col w-full gap-1" style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 10 }}>
          {runs.map((run) => (
            <div key={run.id} className="row w-full items-center gap-2 wrap">
              <Badge tone={run.status === 'error' ? 'danger' : 'ok'}>{run.status}</Badge>
              <span className="ink-small">{formatDatetime(run.finished_at)}</span>
              <span
                className="ink-small"
                style={run.status === 'error' ? { color: 'var(--ink-danger)' } : undefined}
              >
                {lastRunSummary(run)}
              </span>
              {run.detail && run.status !== 'error' && (
                <span className="ink-small truncate" style={{ opacity: 0.7, flex: '1 1 auto' }}>
                  {run.detail}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      <ConfirmDialog
        open={confirmDelete}
        message={deleteMessage}
        destructive
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false)
          deleteMutation.mutate()
        }}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}
