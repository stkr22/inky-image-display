// Immich sync-job create/edit form.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button, Icon, NumberField, RefMultiSelect, SelectField, Slider, Switch, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'

const MIN_COUNT = 1
const MAX_COUNT = 1000

export function SyncJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const notify = useNotify()
  const isEdit = Boolean(jobId)

  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  // Name lookups via the API's Immich proxy. `retry: false` because a 503
  // means "not configured" — the pickers then fall back to free-text IDs.
  const immichQueryOpts = { retry: false, staleTime: 5 * 60_000 } as const
  const { data: albums } = useQuery({ queryKey: ['immich', 'albums'], queryFn: api.listImmichAlbums, ...immichQueryOpts })
  const { data: people } = useQuery({ queryKey: ['immich', 'people'], queryFn: api.listImmichPeople, ...immichQueryOpts })
  const { data: tags } = useQuery({ queryKey: ['immich', 'tags'], queryFn: api.listImmichTags, ...immichQueryOpts })
  const { data: job, isPending: jobPending } = useQuery({
    queryKey: ['sync-job', jobId],
    queryFn: () => api.getSyncJob(jobId!),
    enabled: isEdit,
  })

  const [name, setName] = useState('')
  const [strategy, setStrategy] = useState('RANDOM')
  const [query, setQuery] = useState('')
  const [targetProfile, setTargetProfile] = useState('')
  const [orientation, setOrientation] = useState('')
  const [count, setCount] = useState<number | ''>(10)
  const [maxImages, setMaxImages] = useState<number | ''>(10)
  const [overfetch, setOverfetch] = useState(3)
  const [randomPick, setRandomPick] = useState(false)
  const [active, setActive] = useState(true)
  const [albumIds, setAlbumIds] = useState<string[]>([])
  const [personIds, setPersonIds] = useState<string[]>([])
  const [tagIds, setTagIds] = useState<string[]>([])
  const [favorite, setFavorite] = useState('')
  const [rating, setRating] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [country, setCountry] = useState('')
  const [takenAfter, setTakenAfter] = useState('')
  const [takenBefore, setTakenBefore] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!job) return
    setName(job.name)
    setStrategy(job.strategy || 'RANDOM')
    setQuery(job.query ?? '')
    setTargetProfile(job.target_device_profile_id)
    setOrientation(job.orientation ?? '')
    setCount(job.count)
    setMaxImages(job.max_images)
    setOverfetch(job.overfetch_multiplier || 3)
    setRandomPick(job.random_pick)
    setActive(job.is_active)
    setAlbumIds(job.album_ids ?? [])
    setPersonIds(job.person_ids ?? [])
    setTagIds(job.tag_ids ?? [])
    setFavorite(job.is_favorite == null ? '' : String(job.is_favorite))
    setRating(typeof job.rating === 'number' ? String(job.rating) : '')
    setCity(job.city ?? '')
    setState(job.state ?? '')
    setCountry(job.country ?? '')
    setTakenAfter(job.taken_after?.slice(0, 10) ?? '')
    setTakenBefore(job.taken_before?.slice(0, 10) ?? '')
  }, [job])

  useEffect(() => {
    if (!isEdit && !targetProfile && profiles?.length) setTargetProfile(profiles[0].id)
  }, [profiles, isEdit, targetProfile])

  if (isEdit && jobPending) return <Spinner />

  const save = async () => {
    if (!name) return setError('Name is required')
    if (!targetProfile) return setError('Target device profile is required')
    const countValue = Number(count)
    if (!Number.isInteger(countValue) || countValue < MIN_COUNT || countValue > MAX_COUNT) {
      return setError(`Count must be between ${MIN_COUNT} and ${MAX_COUNT}`)
    }
    const maxImagesValue = Number(maxImages)
    if (!Number.isInteger(maxImagesValue) || maxImagesValue < 0) {
      return setError('Max images must be 0 (unlimited) or greater')
    }
    if (strategy === 'SMART' && !query.trim()) return setError('Query is required when strategy is SMART')

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
      is_favorite: favorite === '' ? null : favorite === 'true',
      city: city || null,
      state: state || null,
      country: country || null,
      taken_after: takenAfter || null,
      taken_before: takenBefore || null,
      rating: rating === '' ? null : Number(rating),
      is_active: active,
    }
    try {
      if (isEdit) await api.updateSyncJob(jobId!, body)
      else await api.createSyncJob(body)
    } catch (err) {
      setError(`Save failed: ${err instanceof ApiError ? err.detail || err.message : err}`)
      return
    }
    notify('Saved', 'positive')
    navigate('/jobs')
  }

  return (
    <>
      <div className="row w-full items-center gap-2">
        <Link to="/jobs" className="ink-btn ink-btn-flat ink-btn-icon" title="Back to jobs">
          <Icon name="arrow_back" />
        </Link>
        <PageHeader
          eyebrow={isEdit ? 'Automations / edit' : 'Automations / new'}
          title={isEdit ? 'Edit sync job' : 'New sync job'}
        />
      </div>

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
            />
            <TextField label="Query (SMART only)" value={query} onChange={setQuery} disabled={strategy !== 'SMART'} />
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
          />
          <div className="ink-form-row items-end w-full">
            <NumberField label={`Count (${MIN_COUNT}-${MAX_COUNT})`} value={count} onChange={setCount} min={MIN_COUNT} max={MAX_COUNT} step={1} />
            <NumberField label="Max images kept (0 = unlimited)" value={maxImages} onChange={setMaxImages} min={0} step={1} />
            <Slider label="Overfetch multiplier" value={overfetch} onChange={setOverfetch} min={1} max={10} />
          </div>
          <div className="row w-full gap-4 items-center wrap">
            <Switch label="Random pick" checked={randomPick} onChange={setRandomPick} />
            <Switch label="Active" checked={active} onChange={setActive} />
          </div>
        </div>
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Immich filters</span>
          <span className="ink-small">Narrow which photos the sync pulls</span>
          <div className="ink-form-row w-full">
            <RefMultiSelect label="Albums" values={albumIds} onChange={setAlbumIds} options={albums} placeholder="Add an album…" />
            <RefMultiSelect label="People" values={personIds} onChange={setPersonIds} options={people} placeholder="Add a person…" />
            <RefMultiSelect label="Tags" values={tagIds} onChange={setTagIds} options={tags} placeholder="Add a tag…" />
          </div>
          {!albums && (
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

      <span className="ink-form-error">{error}</span>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate('/jobs')}>
          Cancel
        </Button>
        <Button primary icon="save" onClick={save}>
          Save
        </Button>
      </div>
    </>
  )
}
