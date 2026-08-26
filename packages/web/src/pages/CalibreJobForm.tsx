// Calibre bookshelf job create/edit form.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, ChipsInput, NumberField, SelectField, Switch, TextField } from '../components/fields'
import { ScheduleEditor, type ScheduleValue } from '../components/ScheduleEditor'
import { useNotify } from '../components/Toast'
import { BackLink, PageHeader, Spinner } from '../components/ui'
import { api, errMessage } from '../lib/api'

export function CalibreJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const notify = useNotify()
  const isEdit = Boolean(jobId)

  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: presets } = useQuery({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })
  const { data: job, isPending: jobPending } = useQuery({
    queryKey: ['calibre-job', jobId],
    queryFn: () => api.getCalibreJob(jobId!),
    enabled: isEdit,
  })

  const [name, setName] = useState('')
  const [mode, setMode] = useState('shelf')
  const [targetProfile, setTargetProfile] = useState('')
  const [presetId, setPresetId] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [languages, setLanguages] = useState<string[]>([])
  const [series, setSeries] = useState<string[]>([])
  const [authors, setAuthors] = useState<string[]>([])
  const [minRating, setMinRating] = useState<number | ''>('')
  const [booksPerShelf, setBooksPerShelf] = useState<number | ''>(6)
  const [imagesPerRun, setImagesPerRun] = useState<number | ''>(1)
  const [retentionDays, setRetentionDays] = useState<number | ''>('')
  const [verifySpines, setVerifySpines] = useState(true)
  const [maxAttempts, setMaxAttempts] = useState<number | ''>(4)
  const [active, setActive] = useState(true)
  const [schedule, setSchedule] = useState<ScheduleValue>({ cron: '0 6 * * 0', timezone: 'UTC' })
  const [error, setError] = useState('')

  const isShelf = mode === 'shelf'

  useEffect(() => {
    if (!job) return
    setName(job.name)
    setMode(job.mode || 'shelf')
    setTargetProfile(job.target_device_profile_id)
    setPresetId(job.prompt_preset_id)
    setTags(job.tags ?? [])
    setLanguages(job.languages ?? [])
    setSeries(job.series ?? [])
    setAuthors(job.authors ?? [])
    setMinRating(typeof job.min_rating === 'number' ? job.min_rating : '')
    setBooksPerShelf(job.books_per_shelf || 6)
    setImagesPerRun(job.images_per_run || 1)
    setRetentionDays(typeof job.retention_days === 'number' ? job.retention_days : '')
    setVerifySpines(job.verify_spines)
    setMaxAttempts(job.max_attempts || 4)
    setActive(job.is_active)
    setSchedule({ cron: job.schedule_cron, timezone: job.schedule_timezone || 'UTC' })
  }, [job])

  useEffect(() => {
    if (!isEdit && !targetProfile && profiles?.length) setTargetProfile(profiles[0].id)
  }, [profiles, isEdit, targetProfile])
  // The migration seeds one preset per mode, so switching mode should follow
  // along rather than leaving a shelf job pointed at the hero prompt.
  useEffect(() => {
    if (isEdit || !presets?.length) return
    const wanted = isShelf ? 'bookshelf_shelf' : 'bookshelf_hero'
    setPresetId(presets.find((p) => p.name === wanted)?.id ?? presets[0].id)
  }, [presets, isEdit, isShelf])

  if (isEdit && jobPending) return <Spinner />

  const save = async () => {
    if (!name) return setError('Name is required')
    if (!targetProfile) return setError('Target device profile is required')
    if (!presetId) return setError('Preset is required')
    const body = {
      name,
      is_active: active,
      schedule_cron: schedule.cron,
      schedule_timezone: schedule.timezone || 'UTC',
      mode,
      target_device_profile_id: targetProfile,
      prompt_preset_id: presetId,
      tags: tags.map((s) => s.trim()).filter(Boolean),
      languages: languages.map((s) => s.trim()).filter(Boolean),
      series: series.map((s) => s.trim()).filter(Boolean),
      authors: authors.map((s) => s.trim()).filter(Boolean),
      min_rating: minRating === '' ? null : Number(minRating),
      books_per_shelf: Number(booksPerShelf) || 6,
      images_per_run: Number(imagesPerRun) || 1,
      retention_days: retentionDays === '' ? null : Number(retentionDays),
      verify_spines: verifySpines,
      max_attempts: Number(maxAttempts) || 4,
    }
    try {
      if (isEdit) await api.updateCalibreJob(jobId!, body)
      else await api.createCalibreJob(body)
    } catch (err) {
      setError(`Save failed: ${errMessage(err)}`)
      return
    }
    notify('Saved', 'positive')
    navigate('/jobs?tab=books')
  }

  return (
    <>
      <div className="row w-full items-center gap-2">
        <BackLink to="/jobs?tab=books" title="Back to jobs" />
        <PageHeader
          eyebrow={isEdit ? 'Bookshelf / edit' : 'Bookshelf / new'}
          title={isEdit ? 'Edit bookshelf job' : 'New bookshelf job'}
        />
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <TextField label="Name" value={name} onChange={setName} />
          <SelectField
            label="Mode"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'shelf', label: 'Shelf — a row of spines (landscape)' },
              { value: 'hero', label: 'Hero — one book’s cover (portrait)' },
            ]}
          />
          <SelectField
            label="Target device profile"
            value={targetProfile}
            onChange={setTargetProfile}
            options={(profiles ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.width}x${p.height})` }))}
          />
          <SelectField
            label="Prompt preset"
            value={presetId}
            onChange={setPresetId}
            options={(presets ?? []).map((p) => ({ value: p.id, label: p.name }))}
          />
          <div className="ink-form-row items-center w-full">
            {isShelf && (
              <NumberField label="Books per shelf" value={booksPerShelf} onChange={setBooksPerShelf} min={2} max={12} step={1} />
            )}
            <NumberField label="Images per run" value={imagesPerRun} onChange={setImagesPerRun} min={1} max={10} step={1} />
            <NumberField
              label="Retention (days, blank = forever)"
              value={retentionDays}
              onChange={setRetentionDays}
              min={0}
              step={1}
            />
          </div>
        </div>
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Which books</span>
          <span className="ink-small">
            Each filter matches any of its values; the filters then combine. Leave a filter empty to place no
            constraint on it. Books are picked at random from whatever matches.
          </span>
          <ChipsInput label="Tags" values={tags} onChange={setTags} placeholder="a Calibre tag — press Enter…" />
          <ChipsInput label="Languages" values={languages} onChange={setLanguages} placeholder="language code, e.g. deu — press Enter…" />
          <ChipsInput label="Series" values={series} onChange={setSeries} placeholder="a series name — press Enter…" />
          <ChipsInput label="Authors" values={authors} onChange={setAuthors} placeholder="an author name — press Enter…" />
          <NumberField label="Minimum rating (1–5, blank = any)" value={minRating} onChange={setMinRating} min={1} max={5} step={1} />
        </div>
      </div>

      {isShelf && (
        <div className="bento-tile w-full" style={{ padding: 24 }}>
          <div className="ink-form-section w-full">
            <span className="ink-eyebrow">Spine check</span>
            <Switch
              label="Verify spine text"
              checked={verifySpines}
              onChange={setVerifySpines}
              help="Reads the finished image back and regenerates when a title or author came out wrong. Costs extra generations but catches misspellings and miscounted books."
            />
            <NumberField label="Attempts before keeping the closest one" value={maxAttempts} onChange={setMaxAttempts} min={1} max={8} step={1} />
          </div>
        </div>
      )}

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Schedule</span>
          <ScheduleEditor value={schedule} onChange={setSchedule} />
          <span className="ink-small">
            Each run spends generation quota, and a shelf that changes daily stops being something you notice.
          </span>
          <Switch
            label="Active"
            checked={active}
            onChange={setActive}
            help="Inactive jobs are skipped by the schedule but can still be started with 'Run now'."
          />
        </div>
      </div>

      <span className="ink-form-error">{error}</span>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate('/jobs?tab=books')}>
          Cancel
        </Button>
        <Button primary icon="save" onClick={save}>
          Save
        </Button>
      </div>
    </>
  )
}
