// Cron schedule editor shared by all job forms and the grid display
// schedule: a preset dropdown that writes a five-field cron expression,
// daily/weekly builders (weekly supports multiple days), a raw cron field
// for power users, and a live "next runs" preview from the API so
// operators see exactly when the schedule will fire before saving.

import { useEffect, useState } from 'react'
import { api, errMessage } from '../lib/api'
import { formatDatetime } from '../lib/format'
import { Button, SelectField, TextField } from './fields'

export interface ScheduleValue {
  cron: string | null
  timezone: string
}

const FIXED_PRESETS = [
  { value: '*/15 * * * *', label: 'Every 15 minutes' },
  { value: '*/30 * * * *', label: 'Every 30 minutes' },
  { value: '0 * * * *', label: 'Hourly' },
  { value: '0 */6 * * *', label: 'Every 6 hours' },
]

// Operator-facing order is Monday-first; values are cron weekdays (0 = Sunday).
const WEEKDAYS = [
  { value: '1', label: 'Mon' },
  { value: '2', label: 'Tue' },
  { value: '3', label: 'Wed' },
  { value: '4', label: 'Thu' },
  { value: '5', label: 'Fri' },
  { value: '6', label: 'Sat' },
  { value: '0', label: 'Sun' },
]

const DAILY_RE = /^(\d{1,2}) (\d{1,2}) \* \* \*$/
const WEEKLY_RE = /^(\d{1,2}) (\d{1,2}) \* \* ([0-6](?:,[0-6])*)$/

type Mode = 'manual' | 'fixed' | 'daily' | 'weekly' | 'custom'

function parseMode(cron: string | null): Mode {
  if (cron == null) return 'manual'
  if (FIXED_PRESETS.some((p) => p.value === cron)) return 'fixed'
  if (DAILY_RE.test(cron)) return 'daily'
  if (WEEKLY_RE.test(cron)) return 'weekly'
  return 'custom'
}

function cronTime(cron: string): string {
  const match = DAILY_RE.exec(cron) ?? WEEKLY_RE.exec(cron)
  if (!match) return '08:00'
  return `${match[2].padStart(2, '0')}:${match[1].padStart(2, '0')}`
}

function cronWeekdays(cron: string): string[] {
  return WEEKLY_RE.exec(cron)?.[3].split(',') ?? ['1']
}

function buildCron(mode: 'daily' | 'weekly', time: string, weekdays: string[]): string {
  const [hours, minutes] = time.split(':')
  const base = `${Number(minutes)} ${Number(hours)} * * `
  if (mode === 'daily') return `${base}*`
  const days = [...weekdays].sort((a, b) => Number(a) - Number(b)).join(',')
  return `${base}${days}`
}

// Human label for list views; falls back to the raw expression for
// anything the presets can't express.
export function describeCron(cron: string | null, timezone: string): string {
  if (cron == null) return 'Manual runs only'
  const fixed = FIXED_PRESETS.find((p) => p.value === cron)
  const tz = timezone === 'UTC' ? '' : ` (${timezone})`
  if (fixed) return `${fixed.label}${tz}`
  if (DAILY_RE.test(cron)) return `Daily at ${cronTime(cron)}${tz}`
  if (WEEKLY_RE.test(cron)) {
    const selected = cronWeekdays(cron)
    const labels = WEEKDAYS.filter((d) => selected.includes(d.value)).map((d) => d.label)
    return `${labels.join(', ')} at ${cronTime(cron)}${tz}`
  }
  return `Cron ${cron}${tz}`
}

export function ScheduleEditor({
  value,
  onChange,
  allowManual = true,
  disabled = false,
}: {
  value: ScheduleValue
  onChange: (next: ScheduleValue) => void
  // Grids keep their own enabled switch, so their editor has no "manual" entry.
  allowManual?: boolean
  disabled?: boolean
}) {
  // Mode is derived from the cron so async form loads just work; the only
  // internal state pins "Custom" while the user types an expression that
  // happens to match a preset shape.
  const [forceCustom, setForceCustom] = useState(false)
  const mode: Mode = forceCustom && value.cron != null ? 'custom' : parseMode(value.cron)
  const [preview, setPreview] = useState<{ runs: string[]; error: string } | null>(null)

  useEffect(() => {
    if (value.cron == null) {
      setPreview(null)
      return
    }
    // Debounced preview so typing in the custom field doesn't spam the API.
    const cron = value.cron
    const handle = setTimeout(async () => {
      try {
        const result = await api.cronPreview(cron, value.timezone)
        setPreview({ runs: result.next_runs, error: '' })
      } catch (err) {
        setPreview({ runs: [], error: errMessage(err) })
      }
    }, 400)
    return () => clearTimeout(handle)
  }, [value.cron, value.timezone])

  const selectValue = mode === 'fixed' ? value.cron! : mode
  const selectSchedule = (selected: string) => {
    setForceCustom(selected === 'custom')
    if (selected === 'manual') onChange({ ...value, cron: null })
    else if (selected === 'daily') onChange({ ...value, cron: buildCron('daily', '08:00', []) })
    else if (selected === 'weekly') onChange({ ...value, cron: buildCron('weekly', '08:00', ['1']) })
    else if (selected === 'custom') onChange({ ...value, cron: value.cron ?? '0 * * * *' })
    else onChange({ ...value, cron: selected })
  }

  const toggleWeekday = (day: string) => {
    const current = cronWeekdays(value.cron!)
    const next = current.includes(day) ? current.filter((d) => d !== day) : [...current, day]
    if (next.length === 0) return // a weekly schedule needs at least one day
    onChange({ ...value, cron: buildCron('weekly', cronTime(value.cron!), next) })
  }

  return (
    <div className="col w-full gap-2">
      <div className="ink-form-row items-end w-full">
        <SelectField
          label="Schedule"
          value={selectValue}
          onChange={selectSchedule}
          disabled={disabled}
          options={[
            ...(allowManual ? [{ value: 'manual', label: 'Manual runs only' }] : []),
            ...FIXED_PRESETS,
            { value: 'daily', label: 'Daily at…' },
            { value: 'weekly', label: 'Weekly on…' },
            { value: 'custom', label: 'Custom cron…' },
          ]}
          help="When this runs automatically. Standard five-field cron under the hood."
        />
        {(mode === 'daily' || mode === 'weekly') && (
          <div className="ink-field">
            <label className="ink-field-label" htmlFor="schedule-time">
              Time
            </label>
            <input
              id="schedule-time"
              type="time"
              className="ink-input"
              disabled={disabled}
              value={cronTime(value.cron!)}
              onChange={(e) =>
                e.target.value &&
                onChange({
                  ...value,
                  cron: buildCron(mode, e.target.value, cronWeekdays(value.cron!)),
                })
              }
            />
          </div>
        )}
        {mode === 'custom' && (
          <TextField
            label="Cron expression"
            value={value.cron ?? ''}
            onChange={(text) => onChange({ ...value, cron: text })}
            placeholder="*/30 8-20 * * 1-5"
            disabled={disabled}
            help="Standard five-field cron: minute, hour, day of month, month, weekday."
          />
        )}
        {value.cron != null && (
          <TextField
            label="Timezone"
            value={value.timezone}
            onChange={(tz) => onChange({ ...value, timezone: tz })}
            placeholder="Europe/Berlin"
            disabled={disabled}
            help="IANA zone the schedule is evaluated in — daily schedules keep their wall-clock time across DST."
          />
        )}
      </div>
      {mode === 'weekly' && (
        <div className="row gap-2 wrap">
          {WEEKDAYS.map((day) => {
            const selected = cronWeekdays(value.cron!).includes(day.value)
            return (
              <Button
                key={day.value}
                flat={!selected}
                primary={selected}
                disabled={disabled}
                onClick={() => toggleWeekday(day.value)}
              >
                {day.label}
              </Button>
            )
          })}
        </div>
      )}
      {preview && !disabled && (
        <span className="ink-small" style={preview.error ? { color: 'var(--ink-danger)' } : undefined}>
          {preview.error
            ? `Invalid schedule: ${preview.error}`
            : `Next runs: ${preview.runs.map((run) => formatDatetime(run)).join(' · ')}`}
        </span>
      )}
    </div>
  )
}
