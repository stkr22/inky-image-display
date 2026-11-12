// Immich sync-job create/edit form.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { NumberField, RefMultiSelect, SelectField, Slider, Switch, TextField } from '../components/fields'
import { JobFormLoader, JobFormShell, useJobSave } from '../components/JobFormShell'
import { ScheduleEditor, type ScheduleValue } from '../components/ScheduleEditor'
import { api, ApiError } from '../lib/api'
import { useDefaultChoice } from '../lib/useDefaultChoice'
import { deviceProfilesQuery } from '../lib/queries'
import type { SyncJob } from '../lib/types'

const MIN_COUNT = 1
const MAX_COUNT = 1000

export function SyncJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  return (
    <JobFormLoader jobId={jobId} queryKey="sync-job" fetchJob={api.getSyncJob} backTo="/jobs" what="sync job">
      {(job) => <SyncJobFields job={job} />}
    </JobFormLoader>
  )
}

function SyncJobFields({ job }: { job: SyncJob | undefined }) {
  const isEdit = job !== undefined
  const { data: profiles } = useQuery(deviceProfilesQuery)
  // Name lookups via the API's Immich proxy. `retry: false` because a 503
  // means "not configured" — the pickers then fall back to free-text IDs.
  // Failures are shown per picker, so they skip the global error toast.
  const immichQueryOpts = { retry: false, staleTime: 5 * 60_000, meta: { silentError: true } } as const
  const { data: albums, error: albumsError } = useQuery({ queryKey: ['immich', 'albums'], queryFn: api.listImmichAlbums, ...immichQueryOpts })
  const { data: people, error: peopleError } = useQuery({ queryKey: ['immich', 'people'], queryFn: api.listImmichPeople, ...immichQueryOpts })
  const { data: tags, error: tagsError } = useQuery({ queryKey: ['immich', 'tags'], queryFn: api.listImmichTags, ...immichQueryOpts })

  const [name, setName] = useState(job?.name ?? '')
  const [strategy, setStrategy] = useState(job?.strategy || 'RANDOM')
  const [query, setQuery] = useState(job?.query ?? '')
  const [targetProfile, setTargetProfile] = useState(job?.target_device_profile_id ?? '')
  const [orientation, setOrientation] = useState(job?.orientation ?? '')
  const [count, setCount] = useState<number | ''>(job?.count ?? 10)
  const [maxImages, setMaxImages] = useState<number | ''>(job?.max_images ?? 10)
  const [overfetch, setOverfetch] = useState(job?.overfetch_multiplier || 3)
  const [randomPick, setRandomPick] = useState(job?.random_pick ?? false)
  const [active, setActive] = useState(job?.is_active ?? true)
  const [schedule, setSchedule] = useState<ScheduleValue>(
    job ? { cron: job.schedule_cron, timezone: job.schedule_timezone || 'UTC' } : { cron: '0 * * * *', timezone: 'UTC' },
  )
  const [albumIds, setAlbumIds] = useState<string[]>(job?.album_ids ?? [])
  const [personIds, setPersonIds] = useState<string[]>(job?.person_ids ?? [])
  const [tagIds, setTagIds] = useState<string[]>(job?.tag_ids ?? [])
  const [albumMatchMode, setAlbumMatchMode] = useState<'all' | 'any'>(job?.album_match_mode ?? 'all')
  const [personMatchMode, setPersonMatchMode] = useState<'all' | 'any'>(job?.person_match_mode ?? 'all')
  const [favorite, setFavorite] = useState(job?.is_favorite == null ? '' : String(job.is_favorite))
  const [rating, setRating] = useState(typeof job?.rating === 'number' ? String(job.rating) : '')
  const [city, setCity] = useState(job?.city ?? '')
  const [state, setState] = useState(job?.state ?? '')
  const [country, setCountry] = useState(job?.country ?? '')
  const [takenAfter, setTakenAfter] = useState(job?.taken_after?.slice(0, 10) ?? '')
  const [takenBefore, setTakenBefore] = useState(job?.taken_before?.slice(0, 10) ?? '')

  useDefaultChoice(!isEdit, targetProfile, setTargetProfile, profiles)
  const { error, saving, fail, submit } = useJobSave({
    jobId: job?.id,
    create: api.createSyncJob,
    update: api.updateSyncJob,
    listKey: ['sync-jobs'],
    detailKey: 'sync-job',
    backTo: '/jobs',
  })

  // 503 means the proxy isn't configured at all — that case gets one shared
  // note below the pickers. Anything else (e.g. a 502 because the Immich API
  // key lacks album.read) is a real failure that can hit one picker while its
  // siblings work, so it's surfaced on the affected field.
  const proxyUnconfigured = albumsError instanceof ApiError && albumsError.statusCode === 503
  const lookupError = (error: unknown): string | undefined => {
    if (!error || (error instanceof ApiError && error.statusCode === 503)) return undefined
    const detail = error instanceof ApiError && error.detail ? error.detail : 'request failed'
    const permissionHint = detail.includes('403') ? ' — the Immich API key likely lacks read access to this list' : ''
    return `Name lookup failed (${detail})${permissionHint}. Enter raw Immich IDs instead.`
  }

  const save = () => {
    if (!name) return fail('Name is required')
    if (!targetProfile) return fail('Target device profile is required')
    const countValue = Number(count)
    if (!Number.isInteger(countValue) || countValue < MIN_COUNT || countValue > MAX_COUNT) {
      return fail(`Count must be between ${MIN_COUNT} and ${MAX_COUNT}`)
    }
    const maxImagesValue = Number(maxImages)
    if (!Number.isInteger(maxImagesValue) || maxImagesValue < 0) {
      return fail('Max images must be 0 (unlimited) or greater')
    }
    if (strategy === 'SMART' && !query.trim()) return fail('Query is required when strategy is SMART')

    const body = {
      name,
      strategy,
      query: strategy === 'SMART' ? query || null : null,
      target_device_profile_id: targetProfile,
      orientation: orientation || null,
      count: countValue,
      max_images: maxImagesValue,
      random_pick: randomPick,
      overfetch_multiplier: overfetch,
      album_ids: albumIds.length ? albumIds : null,
      person_ids: personIds.length ? personIds : null,
      tag_ids: tagIds.length ? tagIds : null,
      album_match_mode: albumMatchMode,
      person_match_mode: personMatchMode,
      is_favorite: favorite === '' ? null : favorite === 'true',
      city: city || null,
      state: state || null,
      country: country || null,
      taken_after: takenAfter || null,
      taken_before: takenBefore || null,
      rating: rating === '' ? null : Number(rating),
      is_active: active,
      schedule_cron: schedule.cron,
      schedule_timezone: schedule.timezone || 'UTC',
    }
    submit(body)
  }

  return (
    <JobFormShell
      backTo="/jobs"
      eyebrow={isEdit ? 'Automations / edit' : 'Automations / new'}
      title={isEdit ? 'Edit sync job' : 'New sync job'}
      error={error}
      saving={saving}
      onSave={save}
    >
      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Basics</span>
          <TextField label="Name" value={name} onChange={setName} />
          <div className="ink-form-row w-full">
            <SelectField
              label="Strategy"
              value={strategy}
              onChange={setStrategy}
              options={[
                { value: 'RANDOM', label: 'RANDOM' },
                { value: 'SMART', label: 'SMART' },
              ]}
              help="RANDOM draws a random sample from all photos matching the filters below. SMART ranks photos by how well they match the query text (semantic search)."
            />
            <TextField
              label="Query (SMART only)"
              value={query}
              onChange={setQuery}
              disabled={strategy !== 'SMART'}
              help="Plain-language description of what the photos should show, e.g. 'kids playing at the beach'. Immich's semantic search matches image content, not just titles or tags."
            />
          </div>
          <SelectField
            label="Target device profile"
            value={targetProfile}
            onChange={setTargetProfile}
            options={(profiles ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.width}x${p.height})` }))}
          />
          <SelectField
            label="Orientation override"
            value={orientation}
            onChange={setOrientation}
            options={[
              { value: '', label: 'Any orientation' },
              { value: 'landscape', label: 'Landscape' },
              { value: 'portrait', label: 'Portrait' },
            ]}
            help="Only photos matching the target shape are synced. 'Any' behaves like the panel's native landscape shape; choose Portrait for portrait-mounted panels — the target dimensions rotate and only portrait photos sync."
          />
          <div className="ink-form-row items-end w-full">
            <NumberField
              label={`Count (${MIN_COUNT}-${MAX_COUNT})`}
              value={count}
              onChange={setCount}
              min={MIN_COUNT}
              max={MAX_COUNT}
              step={1}
              help="How many new images each run tries to add to the library."
            />
            <NumberField
              label="Max images kept (0 = unlimited)"
              value={maxImages}
              onChange={setMaxImages}
              min={0}
              step={1}
              help="Cap on the total images this job keeps in the library (only its own uploads count). At the cap, runs skip until retention deletes older images and frees the budget."
            />
            <Slider
              label="Overfetch multiplier"
              value={overfetch}
              onChange={setOverfetch}
              min={1}
              max={10}
              help="Fetches Count × this many candidates from Immich, because photos with the wrong orientation or too small for the panel are dropped afterwards. Raise it when runs deliver fewer images than requested."
            />
          </div>
          <Switch
            label="Random pick"
            checked={randomPick}
            onChange={setRandomPick}
            help="SMART only: pick the images at random from the fetched search results instead of always taking the closest matches — adds variety between runs. RANDOM jobs are already random."
          />
        </div>
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Schedule</span>
          <ScheduleEditor value={schedule} onChange={setSchedule} />
          <Switch
            label="Active"
            checked={active}
            onChange={setActive}
            help="Inactive jobs are skipped by the schedule but can still be started with 'Run now'."
          />
        </div>
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Immich filters</span>
          <span className="ink-small">Narrow which photos the sync pulls</span>
          <div className="ink-form-row w-full">
            <div className="ink-form-section">
              <RefMultiSelect
                label="Albums"
                values={albumIds}
                onChange={setAlbumIds}
                options={albums}
                placeholder="Add an album…"
                error={lookupError(albumsError)}
                help="Limit to photos from these albums. With several albums, the match rule decides whether a photo must be in all of them or just one."
              />
              {albumIds.length > 1 && (
                <SelectField
                  label="Album match rule"
                  value={albumMatchMode}
                  onChange={(v) => setAlbumMatchMode(v as 'all' | 'any')}
                  options={[
                    { value: 'all', label: 'Must be in every album (AND)' },
                    { value: 'any', label: 'In any selected album (OR)' },
                  ]}
                  help="AND keeps only photos present in every selected album — often very few. OR pulls photos from each of the albums."
                />
              )}
            </div>
            <div className="ink-form-section">
              <RefMultiSelect
                label="People"
                values={personIds}
                onChange={setPersonIds}
                options={people}
                placeholder="Add a person…"
                error={lookupError(peopleError)}
                help="Limit to photos showing these people. With several people, the match rule decides whether a photo must show all of them together or any one of them."
              />
              {personIds.length > 1 && (
                <SelectField
                  label="People match rule"
                  value={personMatchMode}
                  onChange={(v) => setPersonMatchMode(v as 'all' | 'any')}
                  options={[
                    { value: 'all', label: 'Must show everyone together (AND)' },
                    { value: 'any', label: 'Shows any of them (OR)' },
                  ]}
                  help="AND keeps only photos where every selected person appears together. OR pulls photos of each person separately."
                />
              )}
            </div>
            <RefMultiSelect
              label="Tags"
              values={tagIds}
              onChange={setTagIds}
              options={tags}
              placeholder="Add a tag…"
              error={lookupError(tagsError)}
              help="RANDOM jobs match photos carrying any selected tag; SMART jobs require all of them."
            />
          </div>
          {proxyUnconfigured && (
            <span className="ink-small">
              Name lookup unavailable (Immich proxy not configured) — enter raw Immich IDs.
            </span>
          )}
          <div className="ink-form-row w-full">
            <SelectField
              label="Favorite filter"
              value={favorite}
              onChange={setFavorite}
              options={[
                { value: '', label: 'Any' },
                { value: 'true', label: 'Favorites only' },
                { value: 'false', label: 'Non-favorites only' },
              ]}
            />
            <SelectField
              label="Rating"
              value={rating}
              onChange={setRating}
              options={[
                { value: '', label: 'Any' },
                ...[0, 1, 2, 3, 4, 5].map((i) => ({ value: String(i), label: `>= ${i}` })),
              ]}
            />
          </div>
          <div className="ink-form-row w-full">
            <TextField label="City" value={city} onChange={setCity} />
            <TextField label="State/Region" value={state} onChange={setState} />
            <TextField label="Country" value={country} onChange={setCountry} />
          </div>
          <div className="ink-form-row w-full">
            <TextField label="Taken after" type="date" value={takenAfter} onChange={setTakenAfter} />
            <TextField label="Taken before" type="date" value={takenBefore} onChange={setTakenBefore} />
          </div>
        </div>
      </div>
    </JobFormShell>
  )
}
