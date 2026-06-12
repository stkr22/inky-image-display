// Port of packages/ui formatting.py — date/interval helpers shared by views.

const DUE_NOW_WINDOW_SECONDS = 30

export function parseDatetime(value: string | null | undefined): Date | null {
  if (!value) return null
  // The API emits offset-aware ISO strings; treat naive strings as UTC for
  // backwards compatibility with older payloads.
  const hasOffset = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value)
  const parsed = new Date(hasOffset ? value : `${value}Z`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatDatetime(value: string | null | undefined, fallback = '—'): string {
  const dt = parseDatetime(value)
  if (!dt) return fallback
  // Local timezone with explicit zone suffix so users on the wrong machine
  // notice instead of silently misreading UTC times as local.
  const base = dt.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  const zone =
    new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
      .formatToParts(dt)
      .find((p) => p.type === 'timeZoneName')?.value ?? ''
  return `${base} ${zone}`.trim()
}

export function formatRelative(value: string | null | undefined, fallback = '—'): string {
  const dt = parseDatetime(value)
  if (!dt) return fallback
  const delta = (dt.getTime() - Date.now()) / 1000
  if (Math.abs(delta) < DUE_NOW_WINDOW_SECONDS) return 'due now'
  const text = humanizeSeconds(Math.abs(Math.trunc(delta)))
  return delta > 0 ? `in ${text}` : `${text} ago`
}

export function humanizeSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remMinutes = minutes % 60
  if (hours < 24) return remMinutes === 0 ? `${hours}h` : `${hours}h ${remMinutes}m`
  const days = Math.floor(hours / 24)
  const remHours = hours % 24
  return remHours === 0 ? `${days}d` : `${days}d ${remHours}h`
}

export function formatIntervalSeconds(value: number | null | undefined, defaultLabel = 'default'): string {
  if (value == null) return defaultLabel
  return humanizeSeconds(Math.trunc(value))
}

export function splitHoursMinutes(seconds: number | null | undefined): [number, number] {
  if (!seconds || seconds < 0) return [0, 0]
  const minutesTotal = Math.floor(seconds / 60)
  return [Math.floor(minutesTotal / 60), minutesTotal % 60]
}
