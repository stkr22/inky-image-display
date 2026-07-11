// Unified jobs listing — Immich + Gemini in one tabbed page. The tab lives in
// the URL (?tab=gemini) so deep links and back/forward work.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog } from '../components/Dialog'
import { Button, Switch } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatDatetime, formatRelative } from '../lib/format'
import type { GeminiJob, SyncJob, SyncJobRun } from '../lib/types'

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

export function Jobs() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const tab = searchParams.get('tab') === 'gemini' ? 'gemini' : 'immich'

  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const profileMap = new Map((profiles ?? []).map((p) => [p.id, p.name]))

  return (
    <>
      <PageHeader
        eyebrow="Automations"
        title="Jobs"
        actions={
          <Button
            primary
            icon="add"
            onClick={() => navigate(tab === 'gemini' ? '/gemini-jobs/new' : '/sync-jobs/new')}
          >
            {tab === 'gemini' ? 'New Gemini job' : 'New Immich job'}
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
      </div>

      {tab === 'immich' ? <ImmichList profileMap={profileMap} /> : <GeminiList profileMap={profileMap} />}
    </>
  )
}

// Latest run per job, from one bulk fetch — the list is pruned server-side
// to ~20 runs per job, so 200 rows covers every job's history head.
function useLatestRuns(jobType: 'immich' | 'gemini'): Map<string, SyncJobRun> {
  const { data: runs } = useQuery({
    queryKey: ['sync-runs', jobType],
    queryFn: () => api.listSyncRuns({ job_type: jobType, limit: 200 }),
    // Runs land whenever the worker cron fires; poll on the same cadence
    // as the schedule view so "Run now" feedback appears without a reload.
    refetchInterval: 15_000,
  })
  const latest = new Map<string, SyncJobRun>()
  for (const run of runs ?? []) {
    if (!latest.has(run.job_id)) latest.set(run.job_id, run) // list is newest-first
  }
  return latest
}

function ImmichList({ profileMap }: { profileMap: Map<string, string> }) {
  const { data: jobs, isPending } = useQuery({
    queryKey: ['sync-jobs'],
    queryFn: api.listSyncJobs,
    refetchInterval: 15_000,
  })
  const latestRuns = useLatestRuns('immich')
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) return <EmptyNote>No Immich sync jobs yet.</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => (
        <ImmichRow key={job.id} job={job} profileMap={profileMap} lastRun={latestRuns.get(job.id) ?? null} />
      ))}
    </div>
  )
}

function ImmichRow({
  job,
  profileMap,
  lastRun,
}: {
  job: SyncJob
  profileMap: Map<string, string>
  lastRun: SyncJobRun | null
}) {
  const navigate = useNavigate()
  const targetName = profileMap.get(job.target_device_profile_id) ?? job.target_device_profile_id
  return (
    <JobRow
      name={job.name}
      summary={`${job.strategy} · count ${job.count} · → ${targetName} · ${job.orientation || 'any orientation'}`}
      updatedAt={job.updated_at}
      isActive={job.is_active}
      lastRun={lastRun}
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
  const latestRuns = useLatestRuns('gemini')
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) return <EmptyNote>No Gemini jobs yet.</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => (
        <GeminiRow key={job.id} job={job} profileMap={profileMap} lastRun={latestRuns.get(job.id) ?? null} />
      ))}
    </div>
  )
}

function GeminiRow({
  job,
  profileMap,
  lastRun,
}: {
  job: GeminiJob
  profileMap: Map<string, string>
  lastRun: SyncJobRun | null
}) {
  const navigate = useNavigate()
  const targetName = profileMap.get(job.target_device_profile_id) ?? job.target_device_profile_id
  const total = (job.subjects?.length ?? 0) * (job.images_per_subject || 1)
  return (
    <JobRow
      name={job.name}
      summary={`${job.orientation || 'portrait'} · ${total} images per run · → ${targetName}`}
      updatedAt={job.updated_at}
      isActive={job.is_active}
      lastRun={lastRun}
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
  updatedAt,
  isActive,
  lastRun,
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
  updatedAt: string
  isActive: boolean
  lastRun: SyncJobRun | null
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
  // Optimistic toggle: flip immediately, roll back on error.
  const [optimisticActive, setOptimisticActive] = useState<boolean | null>(null)
  const shownActive = optimisticActive ?? isActive

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
    <div className="bento-tile w-full" style={{ padding: '16px 20px', flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <div className="col flex-1 gap-1">
        <div className="row items-center gap-2 wrap">
          <h3 className="ink-h3 truncate">{name}</h3>
          {runQueued && <Badge tone="accent">Run queued</Badge>}
          {lastRun?.status === 'error' && <Badge tone="danger">Last run failed</Badge>}
        </div>
        <span className="ink-small">{summary}</span>
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
