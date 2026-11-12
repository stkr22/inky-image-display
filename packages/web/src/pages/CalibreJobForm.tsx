// Calibre bookshelf job create/edit form.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ChipsInput, NumberField, SelectField, Switch, TextField } from '../components/fields'
import { JobFormLoader, JobFormShell, useJobSave } from '../components/JobFormShell'
import { ScheduleEditor, type ScheduleValue } from '../components/ScheduleEditor'
import { api } from '../lib/api'
import { useDefaultChoice } from '../lib/useDefaultChoice'
import { deviceProfilesQuery, promptPresetsQuery } from '../lib/queries'
import type { CalibreJob } from '../lib/types'

const BACK_TO = '/jobs?tab=books'

export function CalibreJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  return (
    <JobFormLoader jobId={jobId} queryKey="calibre-job" fetchJob={api.getCalibreJob} backTo={BACK_TO} what="bookshelf job">
      {(job) => <CalibreJobFields job={job} />}
    </JobFormLoader>
  )
}

function CalibreJobFields({ job }: { job: CalibreJob | undefined }) {
  const isEdit = job !== undefined
  const { data: profiles } = useQuery(deviceProfilesQuery)
  const { data: presets } = useQuery(promptPresetsQuery)

  const [name, setName] = useState(job?.name ?? '')
  const [mode, setMode] = useState(job?.mode || 'shelf')
  const [targetProfile, setTargetProfile] = useState(job?.target_device_profile_id ?? '')
  const [presetId, setPresetId] = useState(job?.prompt_preset_id ?? '')
  const [tags, setTags] = useState<string[]>(job?.tags ?? [])
  const [languages, setLanguages] = useState<string[]>(job?.languages ?? [])
  const [authors, setAuthors] = useState<string[]>(job?.authors ?? [])
  const [booksPerShelf, setBooksPerShelf] = useState<number | ''>(job?.books_per_shelf || 6)
  const [shelfRows, setShelfRows] = useState<number | ''>(job?.shelf_rows || 3)
  const [avoidRepeats, setAvoidRepeats] = useState(job?.avoid_repeats ?? true)
  const [imagesPerRun, setImagesPerRun] = useState<number | ''>(job?.images_per_run || 1)
  const [retentionDays, setRetentionDays] = useState<number | ''>(
    typeof job?.retention_days === 'number' ? job.retention_days : '',
  )
  const [verifySpines, setVerifySpines] = useState(job?.verify_spines ?? true)
  const [maxAttempts, setMaxAttempts] = useState<number | ''>(job?.max_attempts || 4)
  const [active, setActive] = useState(job?.is_active ?? true)
  const [schedule, setSchedule] = useState<ScheduleValue>(
    job ? { cron: job.schedule_cron, timezone: job.schedule_timezone || 'UTC' } : { cron: '0 6 * * 0', timezone: 'UTC' },
  )

  const isHero = mode === 'hero'
  const isCase = mode === 'bookcase'

  useDefaultChoice(!isEdit, targetProfile, setTargetProfile, profiles)
  // The migration seeds one preset per mode, so switching mode should follow
  // along rather than leaving a shelf job pointed at the hero prompt.
  useEffect(() => {
    if (isEdit || !presets?.length) return
    const wanted = isHero ? 'bookshelf_hero' : isCase ? 'bookshelf_bookcase' : 'bookshelf_shelf'
    setPresetId(presets.find((p) => p.name === wanted)?.id ?? presets[0].id)
  }, [presets, isEdit, isHero, isCase])
  const { error, saving, fail, submit } = useJobSave({
    jobId: job?.id,
    create: api.createCalibreJob,
    update: api.updateCalibreJob,
    listKey: ['calibre-jobs'],
    detailKey: 'calibre-job',
    backTo: BACK_TO,
  })

  const save = () => {
    if (!name) return fail('Name is required')
    if (!targetProfile) return fail('Target device profile is required')
    if (!presetId) return fail('Preset is required')
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
      authors: authors.map((s) => s.trim()).filter(Boolean),
      books_per_shelf: Number(booksPerShelf) || 6,
      shelf_rows: Number(shelfRows) || 3,
      avoid_repeats: avoidRepeats,
      images_per_run: Number(imagesPerRun) || 1,
      retention_days: retentionDays === '' ? null : Number(retentionDays),
      verify_spines: verifySpines,
      max_attempts: Number(maxAttempts) || 4,
    }
    submit(body)
  }

  return (
    <JobFormShell
      backTo={BACK_TO}
      eyebrow={isEdit ? 'Bookshelf / edit' : 'Bookshelf / new'}
      title={isEdit ? 'Edit bookshelf job' : 'New bookshelf job'}
      error={error}
      saving={saving}
      onSave={save}
    >
      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <TextField label="Name" value={name} onChange={setName} />
          <SelectField
            label="Mode"
            value={mode}
            onChange={setMode}
            options={[
              { value: 'shelf', label: 'Shelf — a row of spines (landscape)' },
              { value: 'bookcase', label: 'Bookcase — stacked shelves of spines (portrait)' },
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
            {!isHero && (
              <NumberField label="Books per shelf" value={booksPerShelf} onChange={setBooksPerShelf} min={2} max={12} step={1} />
            )}
            {isCase && (
              <NumberField label="Shelves per image" value={shelfRows} onChange={setShelfRows} min={2} max={5} step={1} />
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
          <ChipsInput label="Authors" values={authors} onChange={setAuthors} placeholder="an author name — press Enter…" />
          <Switch
            label="Avoid duplicate books"
            checked={avoidRepeats}
            onChange={setAvoidRepeats}
            help="Skips books already shown on an image that still exists, from any bookshelf job, so a book is never on two walls at once. A book becomes available again when its image is deleted or expires; set a retention period to rotate books back in. If every matching book is in use the run reports that and generates nothing."
          />
        </div>
      </div>

      {!isHero && (
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
    </JobFormShell>
  )
}
