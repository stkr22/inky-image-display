// Message of the day: configure the generated daily story (prompt, source
// mode, image style), assign one content part per device, schedule/trigger
// the display, and browse/redisplay the stories of the last seven days.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button, NumberField, SelectField, Switch, TextArea, TextField } from '../components/fields'
import { useNotify } from '../components/Toast'
import { Badge, EmptyNote, PageHeader, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { formatRelative, parseDatetime } from '../lib/format'
import {
  MOTD_COMPOUND_PARTS,
  MOTD_PART_LABELS,
  MOTD_PARTS,
  mediaUrl,
  type Device,
  type MotdConfig,
  type MotdMessage,
} from '../lib/types'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const PART_CHOICES = [...MOTD_PARTS, ...MOTD_COMPOUND_PARTS]

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.detail || err.message : String(err)
}

// Time-of-day in unambiguous 24h format (locale time strings may be 12h).
function formatTime24(value: string | null | undefined): string {
  const dt = parseDatetime(value)
  if (!dt) return '—'
  return dt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
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
      <MessagesSection />
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
    queryClient.invalidateQueries({ queryKey: ['motd-messages'] })
    queryClient.invalidateQueries({ queryKey: ['motd-config'] })
  }

  const generate = async () => {
    setBusy(true)
    try {
      await api.motdGenerate()
      notify('Generation started — watch its progress in the story list below.', 'positive')
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
      if (result.skipped_no_content.length) notes.push(`nothing to show: ${result.skipped_no_content.join(', ')}`)
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
            Active{status.active_expires_at ? ` until ${formatTime24(status.active_expires_at)}` : ' until released'}
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

// Explicit 24h hour/minute inputs: the native time input renders 12h on
// AM/PM-locale browsers, and the operator wants 24h everywhere.
function DisplayTimeFields({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const [hour = 8, minute = 0] = value.split(':').map((piece) => Number(piece) || 0)
  const pad = (n: number) => String(n).padStart(2, '0')
  const clamp = (n: number | '', max: number) => Math.min(Math.max(Number(n) || 0, 0), max)
  return (
    <>
      <NumberField
        label="Display hour (24h)"
        value={hour}
        onChange={(v) => onChange(`${pad(clamp(v, 23))}:${pad(minute)}`)}
        min={0}
        max={23}
        disabled={disabled}
        className="flex-1"
      />
      <NumberField
        label="Minute"
        value={minute}
        onChange={(v) => onChange(`${pad(hour)}:${pad(clamp(v, 59))}`)}
        min={0}
        max={59}
        disabled={disabled}
        className="flex-1"
      />
    </>
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
  // One part per display (single or a "two texts on one screen" combo).
  const [assignments, setAssignments] = useState<Record<string, string>>(() =>
    Object.fromEntries(config.assignments.map((a) => [a.device_id, a.parts[0] ?? 'what'])),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const toggleDevice = (device: Device, participating: boolean) => {
    setAssignments((prev) => {
      const next = { ...prev }
      if (participating) next[device.id] = next[device.id] ?? 'what'
      else delete next[device.id]
      return next
    })
  }

  const save = async () => {
    if (!prompt.trim()) return setError('The content prompt is required')
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
        assignments: Object.entries(assignments).map(([device_id, part]) => ({ device_id, parts: [part] })),
      })
      notify('Message of the day configuration saved.', 'positive')
      queryClient.invalidateQueries({ queryKey: ['motd-config'] })
      queryClient.invalidateQueries({ queryKey: ['motd-status'] })
    } catch (err) {
      setError(`Save failed: ${errMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="col w-full gap-4">
      <div className="row w-full gap-4 wrap items-stretch">
        <div className="bento-tile col gap-3 flex-1" style={{ padding: 20, minWidth: 340 }}>
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

        <div className="bento-tile col gap-3 flex-1" style={{ padding: 20, minWidth: 340 }}>
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
            <DisplayTimeFields value={displayTime} onChange={setDisplayTime} disabled={!scheduleEnabled} />
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
          <div className="flex-1" />
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
      </div>

      <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
        <div className="col gap-0">
          <span className="ink-eyebrow">Screens</span>
          <h3 className="ink-h3">Which display shows which part?</h3>
        </div>
        <span className="ink-small">
          Each display shows one part of the story. Combined parts like “What + Why” put two short texts on one
          screen.
        </span>
        {!devices?.length && <EmptyNote>No devices registered yet.</EmptyNote>}
        {(devices ?? []).map((device) => {
          const participating = device.id in assignments
          return (
            <div
              key={device.id}
              className="row w-full items-center gap-3 wrap"
              style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 12 }}
            >
              <Switch checked={participating} onChange={(v) => toggleDevice(device, v)} label={device.device_id} />
              <Badge tone={device.is_online ? 'ok' : 'muted'}>{device.is_online ? 'online' : 'offline'}</Badge>
              <span className="ink-small">
                {device.room ?? ''} · {device.display_orientation}
              </span>
              <div className="flex-1" />
              {participating && (
                <SelectField
                  value={assignments[device.id]}
                  onChange={(part) => setAssignments((prev) => ({ ...prev, [device.id]: part }))}
                  className="motd-part-select"
                  options={PART_CHOICES.map((part) => ({ value: part, label: MOTD_PART_LABELS[part] }))}
                />
              )}
            </div>
          )
        })}
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

// --- Story history (last 7 days) --------------------------------------------------

function MessagesSection() {
  const notify = useNotify()
  const queryClient = useQueryClient()
  const { data: messages } = useQuery({
    queryKey: ['motd-messages'],
    queryFn: () => api.listMotdMessages(10),
    // Poll quickly while a generation is running so the progress row updates.
    refetchInterval: (query) => (query.state.data?.some((m) => m.status === 'generating') ? 3000 : 30_000),
  })
  const { data: status } = useQuery({ queryKey: ['motd-status'], queryFn: api.getMotdStatus })
  const [busy, setBusy] = useState(false)
  // undefined = "no manual choice yet" → the newest story starts expanded.
  const [expandedId, setExpandedId] = useState<string | null | undefined>(undefined)

  const display = async (message: MotdMessage) => {
    setBusy(true)
    try {
      const result = await api.motdDisplay(message.id)
      notify(
        `“${message.headline ?? 'Story'}” started — ${result.displayed.length ? `showing on ${result.displayed.join(', ')}` : 'no devices pushed'}.`,
        'positive',
      )
      queryClient.invalidateQueries({ queryKey: ['motd-status'] })
      queryClient.invalidateQueries({ queryKey: ['motd-messages'] })
    } catch (err) {
      notify(`Display failed: ${errMessage(err)}`, 'negative')
    } finally {
      setBusy(false)
    }
  }

  const openId = expandedId === undefined ? messages?.[0]?.id : expandedId

  return (
    <div className="bento-tile w-full col gap-3" style={{ padding: 20 }}>
      <div className="col gap-0">
        <span className="ink-eyebrow">Stories</span>
        <h3 className="ink-h3">Last 7 days</h3>
      </div>
      <span className="ink-small">
        Generated stories are kept for seven days — click one to preview it, or display it again. “Shown” tells you
        which stories were already on the panels.
      </span>
      {!messages?.length && <EmptyNote>No stories generated yet — use “Generate now” above.</EmptyNote>}
      {(messages ?? []).map((message) => {
        const open = openId === message.id
        const showing = status?.active && status.message_id === message.id
        return (
          <div
            key={message.id}
            className="col w-full gap-2"
            style={{ borderTop: '1px solid var(--ink-border)', paddingTop: 12 }}
          >
            <div
              className="row w-full items-center gap-3 wrap"
              style={{ cursor: 'pointer' }}
              onClick={() => setExpandedId(open ? null : message.id)}
            >
              {message.status === 'generating' && (
                <span className="row items-center gap-2">
                  <div className="ink-spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                  <Badge tone="accent">Generating…</Badge>
                </span>
              )}
              {message.status === 'failed' && <Badge tone="warn">Failed</Badge>}
              <span className="ink-body" style={{ fontWeight: 600 }}>
                {message.headline ?? (message.status === 'generating' ? 'New story on its way…' : 'Untitled story')}
              </span>
              <span className="ink-small">{formatRelative(message.created_at)}</span>
              <div className="flex-1" />
              {showing ? (
                <Badge tone="ok">Showing now</Badge>
              ) : message.displayed_at ? (
                <span className="ink-small">shown {formatRelative(message.displayed_at)}</span>
              ) : (
                message.status === 'ready' && <Badge tone="muted">not shown yet</Badge>
              )}
              {message.status === 'ready' && !showing && (
                <Button
                  flat
                  disabled={busy}
                  onClick={(event) => {
                    event.stopPropagation()
                    display(message)
                  }}
                >
                  Display
                </Button>
              )}
            </div>
            {open && <MessagePreview message={message} />}
          </div>
        )
      })}
    </div>
  )
}

function MessagePreview({ message }: { message: MotdMessage }) {
  return (
    <div className="col w-full gap-2">
      {message.error && <span className="ink-form-error">{message.error}</span>}
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
