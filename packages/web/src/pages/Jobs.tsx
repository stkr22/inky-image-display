// Unified jobs listing — Immich + Gemini in one tabbed page. The tab lives in
// the URL (?tab=gemini) so deep links and back/forward work.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ConfirmDialog } from '../components/Dialog'
import { Button, Switch } from '../components/fields'
import { useNotify } from '../components/Toast'
import { EmptyNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatDatetime } from '../lib/format'
import type { GeminiJob, SyncJob } from '../lib/types'

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

function ImmichList({ profileMap }: { profileMap: Map<string, string> }) {
  const { data: jobs, isPending } = useQuery({ queryKey: ['sync-jobs'], queryFn: api.listSyncJobs })
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) return <EmptyNote>No Immich sync jobs yet.</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => <ImmichRow key={job.id} job={job} profileMap={profileMap} />)}
    </div>
  )
}

function ImmichRow({ job, profileMap }: { job: SyncJob; profileMap: Map<string, string> }) {
  const navigate = useNavigate()
  const targetName = profileMap.get(job.target_device_profile_id) ?? job.target_device_profile_id
  return (
    <JobRow
      name={job.name}
      summary={`${job.strategy} · count ${job.count} · → ${targetName} · ${job.orientation || 'any orientation'}`}
      updatedAt={job.updated_at}
      isActive={job.is_active}
      queryKey={['sync-jobs']}
      onToggle={(value) => api.updateSyncJob(job.id, { is_active: value })}
      onEdit={() => navigate(`/sync-jobs/${job.id}`)}
      onDelete={() => api.deleteSyncJob(job.id)}
      deleteMessage={`Delete sync job '${job.name}'?`}
    />
  )
}

function GeminiList({ profileMap }: { profileMap: Map<string, string> }) {
  const { data: jobs, isPending } = useQuery({ queryKey: ['gemini-jobs'], queryFn: api.listGeminiJobs })
  if (isPending) return <Spinner />
  if (!jobs || jobs.length === 0) return <EmptyNote>No Gemini jobs yet.</EmptyNote>
  return (
    <div className="col w-full gap-2">
      {jobs.map((job) => <GeminiRow key={job.id} job={job} profileMap={profileMap} />)}
    </div>
  )
}

function GeminiRow({ job, profileMap }: { job: GeminiJob; profileMap: Map<string, string> }) {
  const navigate = useNavigate()
  const targetName = profileMap.get(job.target_device_profile_id) ?? job.target_device_profile_id
  const total = (job.subjects?.length ?? 0) * (job.images_per_subject || 1)
  return (
    <JobRow
      name={job.name}
      summary={`${job.orientation || 'portrait'} · ${total} images per run · → ${targetName}`}
      updatedAt={job.updated_at}
      isActive={job.is_active}
      queryKey={['gemini-jobs']}
      onToggle={(value) => api.updateGeminiJob(job.id, { is_active: value })}
      onEdit={() => navigate(`/gemini-jobs/${job.id}`)}
      onDelete={() => api.deleteGeminiJob(job.id)}
      deleteMessage={`Delete Gemini job '${job.name}'?`}
    />
  )
}

function JobRow({
  name,
  summary,
  updatedAt,
  isActive,
  queryKey,
  onToggle,
  onEdit,
  onDelete,
  deleteMessage,
}: {
  name: string
  summary: string
  updatedAt: string
  isActive: boolean
  queryKey: string[]
  onToggle: (value: boolean) => Promise<unknown>
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

  return (
    <div className="bento-tile w-full" style={{ padding: '16px 20px', flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <div className="col flex-1 gap-1">
        <h3 className="ink-h3 truncate">{name}</h3>
        <span className="ink-small">{summary}</span>
        <span className="ink-small">Updated {formatDatetime(updatedAt)}</span>
      </div>
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
