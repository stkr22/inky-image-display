// Message of the day: configure the generated daily story (prompt, source
// mode, image style), assign content parts to devices, schedule/trigger the
// display, and preview the latest generated message.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button, NumberField, SelectField, Switch, TextArea, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatRelative } from '../lib/format'
import {
  MOTD_COMPOUND_PARTS,
  MOTD_PART_LABELS,
  MOTD_PARTS,
  mediaUrl,
  type Device,
  type MotdConfig,
} from '../lib/types'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const PART_CHOICES = [...MOTD_PARTS, ...MOTD_COMPOUND_PARTS]

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

export function Motd() {
  const { data: config } = useQuery({ queryKey: ['motd-config'], queryFn: api.getMotdConfig })

  return (
    <div className="col w-full gap-4">
      <PageHeader eyebrow="Message of the day" title="Daily positive story">
        <p className="ink-body ink-muted" style={{ maxWidth: 640, margin: 0 }}>
          Every day one uplifting story — science, community achievements, everyday heroism — is generated and split
          into short screens (What? Why? When? plus an AI illustration and a QR code with the source) across your
          displays.
        </p>
      </PageHeader>
      <ActionsSection />
      {config ? <ConfigSection config={config} /> : <Spinner />}
      <PreviewSection />
    </div>
  )
}

// --- Actions + live status -----------------------------------------------------

function ActionsSection() {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: status } = useQuery({
    queryKey: ['motd-status'],
    queryFn: api.getMotdStatus,
    refetchInterval: 15_000,
  })
  const [busy, setBusy] = useState(false)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['motd-status'] })
    queryClient.invalidateQueries({ queryKey: ['motd-latest'] })
    queryClient.invalidateQueries({ queryKey: ['motd-config'] })
  }

  const generate = async () => {
    setBusy(true)
    try {
      await api.motdGenerate()
      notify('Generation queued — the preview below updates when it finishes.', 'positive')
      refresh()
    } catch (err) {
      notify(`Generation failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const display = async () => {
    setBusy(true)
    try {
      const result = await api.motdDisplay()
      const notes: string[] = []
      if (result.displayed.length) notes.push(`showing on ${result.displayed.join(', ')}`)
      if (result.offline.length) notes.push(`offline: ${result.offline.join(', ')}`)
      if (result.skipped_grid_claimed.length) notes.push(`grid-claimed: ${result.skipped_grid_claimed.join(', ')}`)
      notify(`Message of the day started — ${notes.join('; ') || 'no devices pushed'}.`, 'positive')
      refresh()
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const release = async () => {
    setBusy(true)
    try {
      await api.motdRelease()
      notify('Released — displays return to normal rotation.', 'positive')
      refresh()
    } catch (err) {
      notify(`Release failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bento-tile w-full" style={{ padding: 20 }}>
      <div className="row w-full items-center gap-3 wrap">
        {status?.active ? (
          <Badge tone="ok">
            Active{status.active_expires_at ? ` until ${new Date(status.active_expires_at).toLocaleTimeString()}` : ' until released'}
          </Badge>
        ) : (
          <Badge tone="muted">Idle</Badge>
        )}
        {status?.active && status.headline && <span className="ink-small">“{status.headline}”</span>}
        <div className="flex-1" />
        <Button onClick={generate} disabled={busy}>
          Generate now
        </Button>
        <Button primary onClick={display} disabled={busy}>
          Display now
        </Button>
        <Button danger onClick={release} disabled={busy || !status?.active}>
          Release
        </Button>
      </div>
      {status?.active && status.devices.length > 0 && (
        <div className="row w-full gap-3 wrap" style={{ marginTop: 8 }}>
          {status.devices.map((device) => (
            <span key={device.device_id} className="ink-small">
              <Badge tone={device.is_online ? 'ok' : 'warn'} /> {device.device_id}:{' '}
              {device.current_part ? (MOTD_PART_LABELS[device.current_part] ?? device.current_part) : '—'}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// --- Configuration --------------------------------------------------------------

function ConfigSection({ config }: { config: MotdConfig }) {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: presets } = useQuery({ queryKey: ['prompt-presets'], queryFn: api.listPromptPresets })
  const { data: devices } = useQuery({ queryKey: ['devices'], queryFn: api.listDevices })

  const [prompt, setPrompt] = useState(config.content_prompt)
  const [sourceMode, setSourceMode] = useState<string>(config.source_mode)
  const [presetId, setPresetId] = useState(config.image_preset_id ?? '')
  const [scheduleEnabled, setScheduleEnabled] = useState(config.schedule_enabled)
  const [displayTime, setDisplayTime] = useState(config.display_time)
  const [weekdayMask, setWeekdayMask] = useState(config.weekday_mask)
  const [timezone, setTimezone] = useState(config.timezone)
  const [leadMinutes, setLeadMinutes] = useState<number | ''>(config.generation_lead_minutes)
  const [untilReleased, setUntilReleased] = useState(config.display_duration_seconds === null)
  const [durationMinutes, setDurationMinutes] = useState<number | ''>(
    config.display_duration_seconds ? Math.round(config.display_duration_seconds / 60) : 60,
  )
  const [assignments, setAssignments] = useState<Record<string, string[]>>(() =>
    Object.fromEntries(config.assignments.map((a) => [a.device_id, a.parts])),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const toggleDevice = (device: Device, participating: boolean) => {
    setAssignments((prev) => {
      const next = { ...prev }
      if (participating) next[device.id] = next[device.id]?.length ? next[device.id] : ['what']
      else delete next[device.id]
      return next
    })
  }

  const togglePart = (deviceId: string, part: string) => {
    setAssignments((prev) => {
      const parts = prev[deviceId] ?? []
      const next = parts.includes(part) ? parts.filter((p) => p !== part) : [...parts, part]
      return { ...prev, [deviceId]: next }
    })
  }

  const save = async () => {
    if (!prompt.trim()) return setError('The content prompt is required')
    const entries = Object.entries(assignments).filter(([, parts]) => parts.length > 0)
    setSaving(true)
    setError('')
    try {
      const durationSeconds = untilReleased ? null : Math.max(Number(durationMinutes) || 0, 1) * 60
      await api.updateMotdConfig({
        content_prompt: prompt.trim(),
        source_mode: sourceMode,
        image_preset_id: presetId || null,
        clear_image_preset: !presetId,
        schedule_enabled: scheduleEnabled,
        display_time: displayTime,
        weekday_mask: weekdayMask,
        timezone,
        generation_lead_minutes: Number(leadMinutes) || 0,
        display_duration_seconds: durationSeconds,
        clear_display_duration: untilReleased,
        assignments: entries.map(([device_id, parts]) => ({ device_id, parts })),
      })
      notify('Message of the day configuration saved.', 'positive')
      queryClient.invalidateQueries({ queryKey: ['motd-config'] })
    } catch (err) {
      setError(`Save failed: ${errMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="col w-full gap-4">
      <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
        <div className="col gap-0">
          <span className="ink-eyebrow">Content</span>
          <h3 className="ink-h3">What kind of story?</h3>
        </div>
        <TextArea
          label="Story themes prompt"
          value={prompt}
          onChange={setPrompt}
          rows={7}
          counter
          maxLength={4000}
        />
        <div className="row gap-2">
          <Button flat onClick={() => setPrompt(config.default_prompt)}>
            Reset to default
          </Button>
        </div>
        <div className="row gap-3 w-full wrap">
          <SelectField
            label="Story source"
            value={sourceMode}
            onChange={setSourceMode}
            className="flex-1"
            options={[
              { value: 'grounded', label: 'Recent news (Google Search grounding, real source links)' },
              { value: 'knowledge', label: 'Timeless stories (model knowledge, no web search)' },
            ]}
          />
          <SelectField
            label="Image style preset"
            value={presetId}
            onChange={setPresetId}
            className="flex-1"
            options={[
              { value: '', label: 'Default preset' },
              ...(presets ?? []).map((preset) => ({ value: preset.id, label: preset.name })),
            ]}
          />
        </div>
        {sourceMode === 'knowledge' && (
          <span className="ink-small">
            Without web search there is no reliable source link, so the QR screen is skipped.
          </span>
        )}
      </div>

      <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
        <div className="col gap-0">
          <span className="ink-eyebrow">Screens</span>
          <h3 className="ink-h3">Which display shows which part?</h3>
        </div>
        <span className="ink-small">
          A display with several parts cycles through them at its refresh interval. Combined parts like “What + When”
          put two short texts on one screen.
        </span>
        {!devices?.length && <EmptyNote>No devices registered yet.</EmptyNote>}
        {(devices ?? []).map((device) => {
          const parts = assignments[device.id] ?? []
          const participating = device.id in assignments
          return (
            <div key={device.id} className="col w-full gap-2" style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 12 }}>
              <div className="row w-full items-center gap-3 wrap">
                <Switch checked={participating} onChange={(v) => toggleDevice(device, v)} label={device.device_id} />
                <Badge tone={device.is_online ? 'ok' : 'muted'}>{device.is_online ? 'online' : 'offline'}</Badge>
                <span className="ink-small">
                  {device.room ?? ''} · {device.display_orientation}
                </span>
              </div>
              {participating && (
                <div className="row gap-2 wrap">
                  {PART_CHOICES.map((part) => {
                    const selected = parts.includes(part)
                    const order = parts.indexOf(part)
                    return (
                      <Button key={part} flat={!selected} primary={selected} onClick={() => togglePart(device.id, part)}>
                        {selected && parts.length > 1 ? `${order + 1}. ` : ''}
                        {MOTD_PART_LABELS[part]}
                      </Button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
        <div className="col gap-0">
          <span className="ink-eyebrow">Schedule</span>
          <h3 className="ink-h3">When and for how long?</h3>
        </div>
        <Switch
          checked={scheduleEnabled}
          onChange={setScheduleEnabled}
          label="Show automatically every day (content is generated ahead of time)"
        />
        <div className="row gap-3 w-full wrap">
          <TextField
            label="Display time"
            type="time"
            value={displayTime}
            onChange={setDisplayTime}
            disabled={!scheduleEnabled}
            className="flex-1"
          />
          <TextField
            label="Timezone (IANA)"
            value={timezone}
            onChange={setTimezone}
            placeholder="Europe/Berlin"
            disabled={!scheduleEnabled}
            className="flex-1"
          />
          <NumberField
            label="Generate ahead (minutes)"
            value={leadMinutes}
            onChange={setLeadMinutes}
            min={0}
            max={1440}
            disabled={!scheduleEnabled}
            className="flex-1"
          />
        </div>
        <div className="row gap-2 wrap">
          {WEEKDAYS.map((day, index) => {
            const selected = Boolean(weekdayMask & (1 << index))
            return (
              <Button
                key={day}
                flat={!selected}
                primary={selected}
                disabled={!scheduleEnabled}
                onClick={() => setWeekdayMask((mask) => mask ^ (1 << index))}
              >
                {day}
              </Button>
            )
          })}
        </div>
        <div className="row gap-3 w-full items-end wrap">
          <Switch checked={untilReleased} onChange={setUntilReleased} label="Show until released manually" />
          {!untilReleased && (
            <NumberField
              label="Duration (minutes)"
              value={durationMinutes}
              onChange={setDurationMinutes}
              min={1}
              className="flex-1"
            />
          )}
        </div>
      </div>

      <div className="row w-full items-center gap-3">
        {error && <span className="ink-form-error">{error}</span>}
        <div className="flex-1" />
        <Button primary onClick={save} disabled={saving}>
          Save configuration
        </Button>
      </div>
    </div>
  )
}

// --- Latest message preview -----------------------------------------------------

function PreviewSection() {
  const { data: message } = useQuery({
    queryKey: ['motd-latest'],
    queryFn: api.getLatestMotdMessage,
    // Poll quickly while a generation is running.
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? 3000 : 30_000),
  })

  if (!message) return null

  return (
    <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
      <div className="row w-full items-center gap-3">
        <div className="col gap-0 flex-1">
          <span className="ink-eyebrow">Preview</span>
          <h3 className="ink-h3">{message.headline ?? 'Latest message'}</h3>
        </div>
        {message.status === 'generating' && <Badge tone="accent">Generating…</Badge>}
        {message.status === 'ready' && <Badge tone="ok">Ready</Badge>}
        {message.status === 'failed' && <Badge tone="warn">Failed</Badge>}
        <span className="ink-small">{formatRelative(message.created_at)}</span>
      </div>
      {message.error && <span className="ink-form-error">{message.error}</span>}
      <div className="col gap-2">
        {(
          [
            ['What?', message.what],
            ['Why?', message.why],
            ['When?', message.when_text],
            ['Takeaway', message.takeaway],
          ] as const
        ).map(
          ([label, text]) =>
            text && (
              <div key={label} className="col gap-0">
                <span className="ink-eyebrow">{label}</span>
                <span className="ink-body">{text}</span>
              </div>
            ),
        )}
        {message.source_url && (
          <span className="ink-small">
            Source:{' '}
            <a href={message.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--ink-accent)' }}>
              {message.source_title ?? message.source_url}
            </a>
          </span>
        )}
      </div>
      {message.screens.length > 0 && (
        <div className="row gap-3 wrap">
          {message.screens.map((screen) => (
            <div key={screen.id} className="col gap-1" style={{ maxWidth: 220 }}>
              <img
                src={mediaUrl(screen.storage_path, 480)}
                alt={`${screen.part} screen`}
                style={{ width: '100%', borderRadius: 8, border: '1px solid var(--ink-border)' }}
              />
              <span className="ink-small">
                {MOTD_PART_LABELS[screen.part] ?? screen.part} · {screen.width}×{screen.height}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
