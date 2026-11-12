// Unified jobs listing — Immich + Gemini + display + bookshelf jobs in one
// tabbed page, with an overview of upcoming and recent runs at the top. The tab
// lives in the URL (?tab=gemini|display|books) so deep links and back/forward work.
//
// The four job types share one list/row implementation driven by JOB_TABS;
// a tab entry only says how to fetch, mutate, link and summarise its jobs.

import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog, Dialog } from '../components/Dialog'
import { Button, Switch, TextField } from '../components/fields'
import { describeCron, ScheduleEditor, type ScheduleValue } from '../components/ScheduleEditor'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, LoadError, PageHeader, Spinner } from '../components/ui'
import { api, errMessage } from '../lib/api'
import { formatDatetime, formatRelative } from '../lib/format'
import { deviceProfilesQuery, gridsQuery } from '../lib/queries'
import type { CalibreJob, DisplayJob, GeminiJob, SyncJob, SyncJobRun } from '../lib/types'

// Fields every job type shares — all the generic list/row code touches.
interface BaseJob {
  id: string
  name: string
  is_active: boolean
  schedule_cron: string | null
  schedule_timezone: string
  next_run_at: string | null
  run_requested_at: string | null
  updated_at: string
}

interface SummaryContext {
  profileName: (id: string) => string
  gridName: (id: string) => string
}

type TabKey = 'immich' | 'gemini' | 'display' | 'books'

interface JobTab<J extends BaseJob> {
  key: TabKey
  label: string
  icon: string
  newLabel: string
  // Run history is recorded under this job_type.
  runType: SyncJobRun['job_type']
  listKey: string[]
  list: () => Promise<J[]>
  update: (id: string, body: Record<string, unknown>) => Promise<unknown>
  runNow: (id: string) => Promise<unknown>
  remove: (id: string) => Promise<unknown>
  editPath: (id: string) => string
  // Absent for display jobs, which are created through a name dialog.
  newPath?: string
  summary: (job: J, ctx: SummaryContext) => string
  deleteMessage: (job: J) => string
  emptyText: string
  nameBadge?: (job: J) => ReactNode
  runNowDisabled?: (job: J) => boolean
  // Display jobs get a quick schedule dialog on the row.
  quickSchedule?: boolean
}

// Erases the job type so the tabs fit one array; safe because each tab's
// callbacks only ever receive jobs from that same tab's list().
function defineTab<J extends BaseJob>(tab: JobTab<J>): JobTab<BaseJob> {
  return tab as unknown as JobTab<BaseJob>
}

// Summarises the filter so the list answers "which books does this pick?"
// without opening the form.
function filterSummary(job: CalibreJob): string {
  const parts = [...(job.tags ?? []), ...(job.authors ?? []), ...(job.languages ?? [])]
  return parts.length ? parts.join(', ') : 'whole library'
}

const JOB_TABS: ReadonlyArray<JobTab<BaseJob>> = [
  defineTab<SyncJob>({
    key: 'immich',
    label: 'Immich',
    icon: 'sync',
    newLabel: 'New Immich job',
    runType: 'immich',
    listKey: ['sync-jobs'],
    list: api.listSyncJobs,
    update: api.updateSyncJob,
    runNow: api.runSyncJobNow,
    remove: api.deleteSyncJob,
    editPath: (id) => `/sync-jobs/${id}`,
    newPath: '/sync-jobs/new',
    summary: (job, ctx) =>
      `${job.strategy} · count ${job.count} · → ${ctx.profileName(job.target_device_profile_id)} · ${job.orientation || 'any orientation'}`,
    deleteMessage: (job) => `Delete sync job '${job.name}'?`,
    emptyText: 'No Immich sync jobs yet.',
  }),
  defineTab<GeminiJob>({
    key: 'gemini',
    label: 'Gemini',
    icon: 'bolt',
    newLabel: 'New Gemini job',
    runType: 'gemini',
    listKey: ['gemini-jobs'],
    list: api.listGeminiJobs,
    update: api.updateGeminiJob,
    runNow: api.runGeminiJobNow,
    remove: api.deleteGeminiJob,
    editPath: (id) => `/gemini-jobs/${id}`,
    newPath: '/gemini-jobs/new',
    summary: (job, ctx) => {
      const total = (job.subjects?.length ?? 0) * (job.images_per_subject || 1)
      return `${job.orientation || 'portrait'} · ${total} images per run · → ${ctx.profileName(job.target_device_profile_id)}`
    },
    deleteMessage: (job) => `Delete Gemini job '${job.name}'?`,
    emptyText: 'No Gemini jobs yet.',
  }),
  defineTab<DisplayJob>({
    key: 'display',
    label: 'Display',
    icon: 'wb_sunny',
    newLabel: 'New display job',
    runType: 'display',
    listKey: ['display-jobs'],
    list: api.listDisplayJobs,
    update: api.updateDisplayJob,
    runNow: api.runDisplayJobNow,
    remove: api.deleteDisplayJob,
    editPath: (id) => `/display-jobs/${id}`,
    summary: (job, ctx) => {
      const target = job.target_grid_id ? `→ ${ctx.gridName(job.target_grid_id)}` : 'no target grid yet'
      return `${job.job_type} · ${target} · ${job.slots.length} slot(s) mapped`
    },
    deleteMessage: (job) => `Delete display job '${job.name}'? Generated groups stay in the library.`,
    emptyText: 'No display jobs yet — create one and point it at a grid.',
    nameBadge: (job) => (!job.target_grid_id ? <Badge tone="warn">No grid</Badge> : null),
    runNowDisabled: (job) => !job.target_grid_id,
    quickSchedule: true,
  }),
  defineTab<CalibreJob>({
    key: 'books',
    label: 'Bookshelf',
    icon: 'menu_book',
    newLabel: 'New bookshelf job',
    runType: 'calibre',
    listKey: ['calibre-jobs'],
    list: api.listCalibreJobs,
    update: api.updateCalibreJob,
    runNow: api.runCalibreJobNow,
    remove: api.deleteCalibreJob,
    editPath: (id) => `/calibre-jobs/${id}`,
    newPath: '/calibre-jobs/new',
    summary: (job, ctx) => {
      const shape =
        job.mode === 'hero'
          ? 'hero cover'
          : job.mode === 'bookcase'
            ? `bookcase of ${job.shelf_rows}×${job.books_per_shelf}`
            : `shelf of ${job.books_per_shelf}`
      return `${shape} · ${job.images_per_run} per run · ${filterSummary(job)} · → ${ctx.profileName(job.target_device_profile_id)}`
    },
    deleteMessage: (job) => `Delete bookshelf job '${job.name}'?`,
    emptyText: 'No bookshelf jobs yet.',
  }),
]

// The overview and the lists poll the same cache entries.
function listQuery(tab: JobTab<BaseJob>) {
  return { queryKey: tab.listKey, queryFn: tab.list, refetchInterval: 15_000 }
}

function scheduleSummary(job: BaseJob): string {
  if (job.schedule_cron == null) return 'Manual runs only'
  const cadence = describeCron(job.schedule_cron, job.schedule_timezone)
  if (job.is_active === false) return `${cadence} (paused)`
  return job.next_run_at ? `${cadence} · next ${formatRelative(job.next_run_at)}` : cadence
}

// A job is waiting for a worker when it is due (Run-now flagged, or
// on-schedule and past its next-run time) — the claim happens on the
// worker cron's next tick.
function isDue(job: { run_requested_at: string | null; is_active: boolean; next_run_at: string | null }): boolean {
  if (job.run_requested_at != null) return true
  return job.is_active && job.next_run_at != null && new Date(job.next_run_at).getTime() <= Date.now()
}

function InlineSpinner() {
  return <div className="ink-spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
}

export function Jobs() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const requested = searchParams.get('tab')
  const tab = JOB_TABS.find((entry) => entry.key === requested) ?? JOB_TABS[0]
  const [createDisplayOpen, setCreateDisplayOpen] = useState(false)

  return (
    <>
      <PageHeader
        eyebrow="Automations"
        title="Jobs"
        actions={
          <Button
            primary
            icon="add"
            onClick={() => (tab.newPath ? navigate(tab.newPath) : setCreateDisplayOpen(true))}
          >
            {tab.newLabel}
          </Button>
        }
      />

      <JobsOverview />

      <div
        className="row w-full gap-2 items-center"
        style={{ borderBottom: '1px solid var(--ink-border)', paddingBottom: 8 }}
      >
        {JOB_TABS.map((entry, index) => (
          <Button
            key={entry.key}
            primary={tab.key === entry.key}
            flat={tab.key !== entry.key}
            icon={entry.icon}
            onClick={() => setSearchParams(index === 0 ? {} : { tab: entry.key })}
          >
            {entry.label}
          </Button>
        ))}
      </div>

      <JobList key={tab.key} tab={tab} />
      {createDisplayOpen && <CreateDisplayJobDialog onClose={() => setCreateDisplayOpen(false)} />}
    </>
  )
}

// --- Overview: upcoming runs and recent executions across all job types ----------

const JOB_TYPE_LABELS = { immich: 'Immich', gemini: 'Gemini', display: 'Display', calibre: 'Bookshelf' } as const

function JobsOverview() {
  const { data: workerStatus } = useQuery({
    queryKey: ['worker-status'],
    queryFn: api.getWorkerStatus,
    refetchInterval: 15_000,
  })
  const { data: runs } = useQuery({
    queryKey: ['sync-runs', 'all'],
    queryFn: () => api.listSyncRuns({ limit: 60 }),
    refetchInterval: 10_000,
  })
  const lists = useQueries({ queries: JOB_TABS.map(listQuery) })
  const allJobs = JOB_TABS.flatMap((tab, index) =>
    (lists[index].data ?? []).map((job) => ({ type: tab.runType, job })),
  )

  const running = (runs ?? []).filter((run) => run.status === 'running')
  const runningJobIds = new Set(running.map((run) => run.job_id))
  const waiting = allJobs.filter(({ job }) => isDue(job) && !runningJobIds.has(job.id))
  const upcoming = allJobs
    .filter(
      ({ job }) =>
        job.is_active && job.next_run_at != null && new Date(job.next_run_at).getTime() > Date.now(),
    )
    .sort((a, b) => new Date(a.job.next_run_at!).getTime() - new Date(b.job.next_run_at!).getTime())
    .slice(0, 6)
  const recent = (runs ?? []).filter((run) => run.status !== 'running').slice(0, 8)

  if (!running.length && !waiting.length && !upcoming.length && !recent.length && workerStatus?.online !== false) {
    return null
  }

  return (
    <div className="ink-card w-full" style={{ gap: 10 }}>
      <div className="row w-full items-center gap-2">
        <h3 className="ink-h3">Overview</h3>
        <div className="flex-1" />
        {workerStatus && (
          <Badge tone={workerStatus.online ? 'ok' : 'danger'}>
            {workerStatus.online ? 'Worker online' : 'Worker offline'}
          </Badge>
        )}
      </div>
      {(running.length > 0 || waiting.length > 0) && (
        <div className="col w-full gap-1">
          {running.map((run) => (
            <div key={run.id} className="row w-full items-center gap-2 wrap">
              <InlineSpinner />
              <Badge tone="accent">In progress</Badge>
              <span className="ink-body">{run.job_name}</span>
              <span className="ink-small">
                {JOB_TYPE_LABELS[run.job_type]} · started {formatRelative(run.started_at)}
              </span>
            </div>
          ))}
          {waiting.map(({ type, job }) => (
            <div key={job.id} className="row w-full items-center gap-2 wrap">
              <Badge tone="warn">Waiting for worker</Badge>
              <span className="ink-body">{job.name}</span>
              <span className="ink-small">{JOB_TYPE_LABELS[type]} · due, not claimed yet</span>
            </div>
          ))}
        </div>
      )}
      {upcoming.length > 0 && (
        <div className="col w-full gap-1" style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 8 }}>
          <span className="ink-eyebrow">Upcoming</span>
          {upcoming.map(({ type, job }) => (
            <div key={job.id} className="row w-full items-center gap-2 wrap">
              <span className="ink-body">{job.name}</span>
              <span className="ink-small">
                {JOB_TYPE_LABELS[type]} · next run {formatRelative(job.next_run_at!)}
              </span>
            </div>
          ))}
        </div>
      )}
      {recent.length > 0 && (
        <div className="col w-full gap-1" style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 8 }}>
          <span className="ink-eyebrow">Recent runs</span>
          {recent.map((run) => (
            <div key={run.id} className="row w-full items-center gap-2 wrap">
              <Badge tone={run.status === 'error' ? 'danger' : 'ok'}>{run.status}</Badge>
              <span className="ink-body">{run.job_name}</span>
              <span className="ink-small">
                {JOB_TYPE_LABELS[run.job_type]} · {run.finished_at ? formatRelative(run.finished_at) : ''} ·{' '}
                {lastRunSummary(run)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Runs per job (newest first), from one bulk fetch — the list is pruned
// server-side to ~20 runs per job, so 200 rows covers every job's history.
function useRunsByJob(jobType: SyncJobRun['job_type']): Map<string, SyncJobRun[]> {
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

function JobList({ tab }: { tab: JobTab<BaseJob> }) {
  const { data: jobs, isPending, isError, error, refetch } = useQuery(listQuery(tab))
  const { data: profiles } = useQuery(deviceProfilesQuery)
  // Only display jobs name a grid; skip the request on the other tabs.
  const { data: grids } = useQuery({ ...gridsQuery, enabled: tab.key === 'display' })
  const runsByJob = useRunsByJob(tab.runType)

  const profileNames = new Map((profiles ?? []).map((p) => [p.id, p.name]))
  const gridNames = new Map((grids ?? []).map((g) => [g.id, g.name]))
  const ctx: SummaryContext = {
    profileName: (id) => profileNames.get(id) ?? id,
    gridName: (id) => gridNames.get(id) ?? 'grid',
  }

  if (isPending) return <Spinner />
  // Without this a failed fetch read as "No … jobs yet".
  if (isError) return <LoadError what={`${tab.label} jobs`} error={error} onRetry={() => refetch()} />
  if (jobs.length === 0) return <EmptyNote>{tab.emptyText}</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => (
        <JobRow key={job.id} tab={tab} job={job} summary={tab.summary(job, ctx)} runs={runsByJob.get(job.id) ?? []} />
      ))}
    </div>
  )
}

// Quick cadence editor straight from the job row — the full form still
// offers it, but "how often does this run?" shouldn't require a page hop.
function DisplayJobScheduleDialog({ job, listKey, onClose }: { job: BaseJob; listKey: string[]; onClose: () => void }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [schedule, setSchedule] = useState<ScheduleValue>({
    cron: job.schedule_cron,
    timezone: job.schedule_timezone || 'UTC',
  })

  const mutation = useMutation({
    mutationFn: () =>
      api.updateDisplayJob(job.id, {
        schedule_cron: schedule.cron,
        schedule_timezone: schedule.timezone || 'UTC',
        clear_schedule: schedule.cron == null,
      }),
    onSuccess: () => {
      notify('Schedule saved.', 'positive')
      queryClient.invalidateQueries({ queryKey: listKey })
      onClose()
    },
    onError: (err) => notify(`Save failed: ${errMessage(err)}`, 'negative'),
  })

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">Schedule '{job.name}'</h3>
      <ScheduleEditor value={schedule} onChange={setSchedule} />
      <span className="ink-small">
        The grid's own display schedule decides when generated content is shown.
      </span>
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          Save
        </Button>
      </div>
    </Dialog>
  )
}

function CreateDisplayJobDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [name, setName] = useState('Message of the day')

  const mutation = useMutation({
    mutationFn: () => api.createDisplayJob({ name }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['display-jobs'] })
      notify('Display job created — pick its target grid next.', 'positive')
      navigate(`/display-jobs/${job.id}`)
      onClose()
    },
    onError: (err) => notify(`Create failed: ${errMessage(err)}`, 'negative'),
  })

  return (
    <Dialog open onClose={onClose}>
      <h3 className="ink-h3">New display job</h3>
      <TextField label="Name" value={name} onChange={setName} />
      <div className="row w-full justify-end gap-2">
        <Button flat onClick={onClose}>
          Cancel
        </Button>
        <Button primary onClick={() => mutation.mutate()} disabled={!name || mutation.isPending}>
          Create
        </Button>
      </div>
    </Dialog>
  )
}

function lastRunSummary(run: SyncJobRun): string {
  if (run.status === 'error') return run.error || 'failed'
  if (run.status === 'running') return 'in progress'
  const parts = [`${run.images_added} added`]
  if (run.images_skipped > 0) parts.push(`${run.images_skipped} skipped`)
  if (run.images_deleted > 0) parts.push(`${run.images_deleted} expired`)
  return parts.join(', ')
}

function JobRow({
  tab,
  job,
  summary,
  runs,
}: {
  tab: JobTab<BaseJob>
  job: BaseJob
  summary: string
  runs: SyncJobRun[]
}) {
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const lastRun = runs[0] ?? null
  const inProgress = lastRun?.status === 'running'
  const waitingForWorker = !inProgress && isDue(job)
  // Returning the invalidation keeps each mutation pending until the list
  // has refetched, so derived UI (the toggle below) never flashes back to
  // the stale server value in between.
  const refreshList = () => queryClient.invalidateQueries({ queryKey: tab.listKey })

  const toggleMutation = useMutation({
    mutationFn: (value: boolean) => tab.update(job.id, { is_active: value }),
    onSuccess: () => {
      notify('Updated', 'positive')
      return refreshList()
    },
    onError: (err) => notify(`Toggle failed: ${errMessage(err)}`, 'negative'),
  })
  // Optimistic toggle derived from the mutation itself: shows the requested
  // value while in flight and falls back to the server value afterwards, so
  // there is no local copy to go stale.
  const shownActive = toggleMutation.isPending ? toggleMutation.variables : job.is_active

  const deleteMutation = useMutation({
    mutationFn: () => tab.remove(job.id),
    onSuccess: () => {
      notify('Deleted', 'positive')
      return refreshList()
    },
    onError: (err) => notify(`Delete failed: ${errMessage(err)}`, 'negative'),
  })

  const runNowMutation = useMutation({
    mutationFn: () => tab.runNow(job.id),
    onSuccess: () => {
      notify('Run queued — the worker is being woken up now', 'positive')
      return refreshList()
    },
    onError: (err) => notify(`Run request failed: ${errMessage(err)}`, 'negative'),
  })
  const runQueued = job.run_requested_at != null
  const name = job.name

  return (
    <div className="bento-tile w-full" style={{ padding: '16px 20px', gap: 12 }}>
      <div className="row w-full items-center" style={{ gap: 12 }}>
        <div className="col flex-1 gap-1">
          <div className="row items-center gap-2 wrap">
            <h3 className="ink-h3 truncate">{name}</h3>
            {tab.nameBadge?.(job)}
            {inProgress && (
              <span className="row items-center gap-2">
                <InlineSpinner />
                <Badge tone="accent">In progress</Badge>
              </span>
            )}
            {!inProgress && waitingForWorker && <Badge tone="warn">Waiting for worker</Badge>}
            {lastRun?.status === 'error' && <Badge tone="danger">Last run failed</Badge>}
          </div>
          <span className="ink-small">{summary}</span>
          <span className="ink-small">{scheduleSummary(job)}</span>
          {lastRun && lastRun.status !== 'running' ? (
            <span
              className="ink-small"
              style={lastRun.status === 'error' ? { color: 'var(--ink-danger)' } : undefined}
            >
              Last run {formatRelative(lastRun.finished_at ?? lastRun.started_at)}: {lastRunSummary(lastRun)}
            </span>
          ) : !lastRun ? (
            <span className="ink-small" style={{ opacity: 0.7 }}>
              No runs recorded yet
            </span>
          ) : null}
          <span className="ink-small">Updated {formatDatetime(job.updated_at)}</span>
        </div>
        <Button
          flat
          round
          icon="history"
          title={historyOpen ? 'Hide run history' : 'Show run history'}
          disabled={runs.length === 0}
          onClick={() => setHistoryOpen((open) => !open)}
        />
        {tab.quickSchedule && (
          <Button flat round icon="schedule" title="Edit schedule" onClick={() => setScheduleOpen(true)} />
        )}
        <Button
          flat
          round
          icon="play_arrow"
          title={runQueued ? 'Run already queued' : 'Run now'}
          disabled={runQueued || tab.runNowDisabled?.(job) || runNowMutation.isPending}
          onClick={() => runNowMutation.mutate()}
        />
        <Switch
          checked={shownActive}
          disabled={toggleMutation.isPending}
          onChange={(value) => toggleMutation.mutate(value)}
        />
        <Button flat round icon="edit" title="Edit" onClick={() => navigate(tab.editPath(job.id))} />
        <Button
          flat
          danger
          round
          icon="delete"
          title="Delete"
          disabled={deleteMutation.isPending}
          onClick={() => setConfirmDelete(true)}
        />
      </div>
      {historyOpen && (
        <div className="col w-full gap-1" style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 10 }}>
          {runs.map((run) => (
            <div key={run.id} className="row w-full items-center gap-2 wrap">
              <Badge tone={run.status === 'error' ? 'danger' : run.status === 'running' ? 'accent' : 'ok'}>
                {run.status}
              </Badge>
              <span className="ink-small">{formatDatetime(run.finished_at ?? run.started_at)}</span>
              <span
                className="ink-small"
                style={run.status === 'error' ? { color: 'var(--ink-danger)' } : undefined}
              >
                {lastRunSummary(run)}
              </span>
              {run.detail && run.status === 'success' && (
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
        message={tab.deleteMessage(job)}
        destructive
        confirmLabel="Delete"
        onConfirm={() => {
          setConfirmDelete(false)
          deleteMutation.mutate()
        }}
        onCancel={() => setConfirmDelete(false)}
      />
      {scheduleOpen && (
        <DisplayJobScheduleDialog job={job} listKey={tab.listKey} onClose={() => setScheduleOpen(false)} />
      )}
    </div>
  )
}
