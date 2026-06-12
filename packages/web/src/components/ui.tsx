// Design-system composition helpers: bento grid, tiles, stats, badges,
// page headers.

import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'

export function BentoGrid({ children }: { children: ReactNode }) {
  return <div className="bento-grid">{children}</div>
}

export function Tile({
  span = 'col-span-6',
  rowSpan,
  to,
  onClick,
  children,
  style,
}: {
  span?: string
  rowSpan?: string
  to?: string
  onClick?: () => void
  children: ReactNode
  style?: CSSProperties
}) {
  const classes = ['bento-tile', span]
  if (rowSpan) classes.push(rowSpan)
  if (to || onClick) classes.push('is-clickable')
  if (to) {
    return (
      <Link to={to} className={classes.join(' ')} style={style}>
        {children}
      </Link>
    )
  }
  return (
    <div className={classes.join(' ')} onClick={onClick} style={style}>
      {children}
    </div>
  )
}

export function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <>
      <span className="ink-stat-label">{label}</span>
      <span className="ink-stat-value ink-numeric">{value}</span>
      {hint && <span className="ink-stat-hint">{hint}</span>}
    </>
  )
}

export type BadgeTone = 'ok' | 'warn' | 'muted' | 'accent' | 'neutral'

// Children are optional: the badge always draws its own status dot via CSS,
// so a bare <Badge tone="ok" /> renders as a dot-only pill.
export function Badge({ children, tone = 'neutral' }: { children?: ReactNode; tone?: BadgeTone }) {
  return <span className={`ink-badge ${tone === 'neutral' ? '' : tone}`}>{children}</span>
}

export function PageHeader({
  eyebrow,
  title,
  actions,
  children,
}: {
  eyebrow: string
  title: string
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="row items-end justify-between w-full wrap gap-3">
      <div className="col gap-0">
        <span className="ink-eyebrow">{eyebrow}</span>
        <h2 className="ink-h2">{title}</h2>
        {children}
      </div>
      {actions && <div className="row gap-2 items-center">{actions}</div>}
    </div>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <span className="ink-empty">{children}</span>
}

export function Spinner() {
  return (
    <div className="row w-full" style={{ justifyContent: 'center', padding: 32 }}>
      <div className="ink-spinner" />
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <span style={{ color: 'var(--ink-danger)', fontSize: 14 }}>{children}</span>
}
