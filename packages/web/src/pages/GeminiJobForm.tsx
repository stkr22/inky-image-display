// Gemini batch-job create/edit form.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ChipsInput, NumberField, SelectField, Switch, TextField } from '../components/fields'
import { JobFormLoader, JobFormShell, useJobSave } from '../components/JobFormShell'
import { ScheduleEditor, type ScheduleValue } from '../components/ScheduleEditor'
import { api } from '../lib/api'
import { useDefaultChoice } from '../lib/useDefaultChoice'
import { deviceProfilesQuery, promptPresetsQuery } from '../lib/queries'
import type { GeminiJob } from '../lib/types'

const BACK_TO = '/jobs?tab=gemini'

export function GeminiJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  return (
    <JobFormLoader jobId={jobId} queryKey="gemini-job" fetchJob={api.getGeminiJob} backTo={BACK_TO} what="Gemini job">
      {(job) => <GeminiJobFields job={job} />}
    </JobFormLoader>
  )
}

function GeminiJobFields({ job }: { job: GeminiJob | undefined }) {
  const isEdit = job !== undefined
  const { data: profiles } = useQuery(deviceProfilesQuery)
  const { data: presets } = useQuery(promptPresetsQuery)

  const [name, setName] = useState(job?.name ?? '')
  const [targetProfile, setTargetProfile] = useState(job?.target_device_profile_id ?? '')
  const [presetId, setPresetId] = useState(job?.prompt_preset_id ?? '')
  const [orientation, setOrientation] = useState(job?.orientation || 'portrait')
  const [imagesPerSubject, setImagesPerSubject] = useState<number | ''>(job?.images_per_subject || 1)
  const [retentionDays, setRetentionDays] = useState<number | ''>(
    typeof job?.retention_days === 'number' ? job.retention_days : '',
  )
  const [subjects, setSubjects] = useState<string[]>(job?.subjects ?? [])
  const [active, setActive] = useState(job?.is_active ?? true)
  const [schedule, setSchedule] = useState<ScheduleValue>(
    job ? { cron: job.schedule_cron, timezone: job.schedule_timezone || 'UTC' } : { cron: '0 0 * * *', timezone: 'UTC' },
  )

  useDefaultChoice(!isEdit, targetProfile, setTargetProfile, profiles)
  useDefaultChoice(!isEdit, presetId, setPresetId, presets)
  const { error, saving, fail, submit } = useJobSave({
    jobId: job?.id,
    create: api.createGeminiJob,
    update: api.updateGeminiJob,
    listKey: ['gemini-jobs'],
    detailKey: 'gemini-job',
    backTo: BACK_TO,
  })

  const save = () => {
    if (!name) return fail('Name is required')
    if (!targetProfile) return fail('Target device profile is required')
    if (!presetId) return fail('Preset is required')
    const cleanSubjects = subjects.map((s) => s.trim()).filter(Boolean)
    if (cleanSubjects.length === 0) return fail('At least one subject is required')
    const body = {
      name,
      is_active: active,
      schedule_cron: schedule.cron,
      schedule_timezone: schedule.timezone || 'UTC',
      target_device_profile_id: targetProfile,
      prompt_preset_id: presetId,
      orientation: orientation || 'portrait',
      subjects: cleanSubjects,
      images_per_subject: Number(imagesPerSubject) || 1,
      retention_days: retentionDays === '' ? null : Number(retentionDays),
    }
    submit(body)
  }

  return (
    <JobFormShell
      backTo={BACK_TO}
      eyebrow={isEdit ? 'AI generation / edit' : 'AI generation / new'}
      title={isEdit ? 'Edit Gemini job' : 'New Gemini job'}
      error={error}
      saving={saving}
      onSave={save}
    >
      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <TextField label="Name" value={name} onChange={setName} />
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
            <SelectField
              label="Orientation"
              value={orientation}
              onChange={setOrientation}
              options={[
                { value: 'portrait', label: 'Portrait' },
                { value: 'landscape', label: 'Landscape' },
              ]}
            />
            <NumberField
              label="Images per subject"
              value={imagesPerSubject}
              onChange={setImagesPerSubject}
              min={1}
              max={10}
              step={1}
            />
            <NumberField
              label="Retention (days, blank = forever)"
              value={retentionDays}
              onChange={setRetentionDays}
              min={0}
              step={1}
            />
          </div>
          <ChipsInput label="Subjects" values={subjects} onChange={setSubjects} placeholder="Add a subject and press Enter…" />
        </div>
      </div>

      <div className="bento-tile w-full" style={{ padding: 24 }}>
        <div className="ink-form-section w-full">
          <span className="ink-eyebrow">Schedule</span>
          <ScheduleEditor value={schedule} onChange={setSchedule} />
          <span className="ink-small">Gemini batches spend generation quota — daily is a sensible default.</span>
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
