// Shared skeleton of the job create/edit forms (Immich sync, Gemini,
// bookshelf): loading the job, the header with back link, the error line and
// the Save/Cancel bar, plus the save mutation. Each form only owns its fields
// and request body.
//
// Two bugs this layout prevents for every form at once:
// - Form state is seeded once per job id. JobFormLoader keys the field
//   component on the job id and the fields use useState initialisers, so a
//   background refetch (window focus, invalidation after "Run now") can't
//   overwrite what the operator is typing.
// - Save is a mutation whose pending state disables the button, so a double
//   click can't create the job twice.

import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { Fragment, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { errMessage } from '../lib/api'
import { Button } from './fields'
import { useNotify } from './Toast'
import { BackLink, DocumentTitle, LoadError, PageHeader, Spinner } from './ui'

export function JobFormLoader<T extends { id: string }>({
  jobId,
  queryKey,
  fetchJob,
  backTo,
  what,
  children,
}: {
  jobId: string | undefined
  // Detail-cache prefix, e.g. 'sync-job' → ['sync-job', jobId].
  queryKey: string
  fetchJob: (id: string) => Promise<T>
  backTo: string
  what: string
  children: (job: T | undefined) => ReactNode
}) {
  const query = useQuery({
    queryKey: [queryKey, jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
    // Nothing on the form would pick up a focus refetch anyway (state is
    // seeded once), so skip the request.
    refetchOnWindowFocus: false,
  })

  if (!jobId) return <Fragment key="new">{children(undefined)}</Fragment>
  if (query.isPending) return <Spinner />
  if (query.isError) {
    return (
      <>
        <DocumentTitle title={`Edit ${what}`} />
        <div className="row w-full items-center gap-2">
          <BackLink to={backTo} title="Back to jobs" />
          <LoadError what={what} error={query.error} onRetry={() => query.refetch()} />
        </div>
      </>
    )
  }
  return <Fragment key={query.data.id}>{children(query.data)}</Fragment>
}

export function useJobSave<B>({
  jobId,
  create,
  update,
  listKey,
  detailKey,
  backTo,
}: {
  jobId: string | undefined
  create: (body: B) => Promise<unknown>
  update: (id: string, body: B) => Promise<unknown>
  listKey: QueryKey
  detailKey: string
  backTo: string
}) {
  const navigate = useNavigate()
  const notify = useNotify()
  const queryClient = useQueryClient()
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: (body: B) => (jobId ? update(jobId, body) : create(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey })
      if (jobId) queryClient.invalidateQueries({ queryKey: [detailKey, jobId] })
      notify('Saved', 'positive')
      navigate(backTo)
    },
    onError: (err) => setError(`Save failed: ${errMessage(err)}`),
  })

  return {
    error,
    saving: mutation.isPending,
    // Validation failures go through the same error line as server errors.
    fail: setError,
    submit: (body: B) => {
      setError('')
      mutation.mutate(body)
    },
  }
}

export function JobFormShell({
  backTo,
  eyebrow,
  title,
  error,
  saving,
  onSave,
  children,
}: {
  backTo: string
  eyebrow: string
  title: string
  error: string
  saving: boolean
  onSave: () => void
  children: ReactNode
}) {
  const navigate = useNavigate()
  return (
    <>
      <div className="row w-full items-center gap-2">
        <BackLink to={backTo} title="Back to jobs" />
        <PageHeader eyebrow={eyebrow} title={title} />
      </div>

      {children}

      <span className="ink-form-error">{error}</span>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate(backTo)}>
          Cancel
        </Button>
        <Button primary icon="save" onClick={onSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </>
  )
}
