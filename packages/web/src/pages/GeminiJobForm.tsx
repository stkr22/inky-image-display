// Gemini batch-job create/edit form.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button, ChipsInput, Icon, NumberField, SelectField, Switch, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'

export function GeminiJobForm() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const notify = useNotify()
  const isEdit = Boolean(jobId)

  const { data: profiles } = useQuery({ queryKey: ['device-profiles'], queryFn: api.listDeviceProfiles })
  const { data: presets } = useQuery({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })
  const { data: job, isPending: jobPending } = useQuery({
    queryKey: ['gemini-job', jobId],
    queryFn: () => api.getGeminiJob(jobId!),
    enabled: isEdit,
  })

  const [name, setName] = useState('')
  const [targetProfile, setTargetProfile] = useState('')
  const [presetId, setPresetId] = useState('')
  const [orientation, setOrientation] = useState('portrait')
  const [imagesPerSubject, setImagesPerSubject] = useState<number | ''>(1)
  const [retentionDays, setRetentionDays] = useState<number | ''>('')
  const [subjects, setSubjects] = useState<string[]>([])
  const [active, setActive] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!job) return
    setName(job.name)
    setTargetProfile(job.target_device_profile_id)
    setPresetId(job.prompt_preset_id)
    setOrientation(job.orientation || 'portrait')
    setImagesPerSubject(job.images_per_subject || 1)
    setRetentionDays(typeof job.retention_days === 'number' ? job.retention_days : '')
    setSubjects(job.subjects ?? [])
    setActive(job.is_active)
  }, [job])

  useEffect(() => {
    if (!isEdit && !targetProfile && profiles?.length) setTargetProfile(profiles[0].id)
  }, [profiles, isEdit, targetProfile])
  useEffect(() => {
    if (!isEdit && !presetId && presets?.length) {
      setPresetId(presets.find((p) => p.is_default)?.id ?? presets[0].id)
    }
  }, [presets, isEdit, presetId])

  if (isEdit && jobPending) return <Spinner />

  const save = async () => {
    if (!name) return setError('Name is required')
    if (!targetProfile) return setError('Target device profile is required')
    if (!presetId) return setError('Preset is required')
    const cleanSubjects = subjects.map((s) => s.trim()).filter(Boolean)
    if (cleanSubjects.length === 0) return setError('At least one subject is required')
    const body = {
      name,
      is_active: active,
      target_device_profile_id: targetProfile,
      prompt_preset_id: presetId,
      orientation: orientation || 'portrait',
      subjects: cleanSubjects,
      images_per_subject: Number(imagesPerSubject) || 1,
      retention_days: retentionDays === '' ? null : Number(retentionDays),
    }
    try {
      if (isEdit) await api.updateGeminiJob(jobId!, body)
      else await api.createGeminiJob(body)
    } catch (err) {
      setError(`Save failed: ${err instanceof ApiError ? err.detail || err.message : err}`)
      return
    }
    notify('Saved', 'positive')
    navigate('/jobs?tab=gemini')
  }

  return (
    <>
      <div className="row w-full items-center gap-2">
        <Link to="/jobs?tab=gemini" className="ink-btn ink-btn-flat ink-btn-icon" title="Back to jobs">
          <Icon name="arrow_back" />
        </Link>
        <PageHeader
          eyebrow={isEdit ? 'AI generation / edit' : 'AI generation / new'}
          title={isEdit ? 'Edit Gemini job' : 'New Gemini job'}
        />
      </div>

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
          <Switch label="Active" checked={active} onChange={setActive} />
        </div>
      </div>

      <span className="ink-form-error">{error}</span>

      <div className="ink-action-bar">
        <Button flat onClick={() => navigate('/jobs?tab=gemini')}>
          Cancel
        </Button>
        <Button primary icon="save" onClick={save}>
          Save
        </Button>
      </div>
    </>
  )
}
