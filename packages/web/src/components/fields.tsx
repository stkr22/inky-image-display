// Native form controls styled to the ink design system. Each one is a thin
// controlled wrapper so pages stay declarative and consistent.

import {
  useId,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'

export function Icon({ name, style }: { name: string; style?: CSSProperties }) {
  return (
    <span className="material-icons" style={style} aria-hidden="true">
      {name}
    </span>
  )
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  primary?: boolean
  ghost?: boolean
  flat?: boolean
  danger?: boolean
  icon?: string
  round?: boolean
}

export function Button({ primary, ghost, flat, danger, icon, round, children, className, ...rest }: ButtonProps) {
  const classes = ['ink-btn']
  if (primary) classes.push('ink-btn-primary')
  if (ghost) classes.push('ink-btn-ghost')
  if (flat) classes.push('ink-btn-flat')
  if (danger) classes.push('ink-btn-danger')
  if (round) classes.push('ink-btn-icon')
  if (className) classes.push(className)
  return (
    <button type="button" className={classes.join(' ')} {...rest}>
      {icon && <Icon name={icon} />}
      {children}
    </button>
  )
}

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  label?: string
  onChange?: (value: string) => void
}

export function TextField({ label, onChange, className, ...rest }: TextFieldProps) {
  const id = useId()
  return (
    <div className={`ink-field ${className ?? ''}`}>
      {label && (
        <label className="ink-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <input id={id} className="ink-input" onChange={(e) => onChange?.(e.target.value)} {...rest} />
    </div>
  )
}

interface NumberFieldProps {
  label?: string
  value: number | ''
  onChange: (value: number | '') => void
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  placeholder?: string
  className?: string
}

export function NumberField({ label, value, onChange, className, ...rest }: NumberFieldProps) {
  const id = useId()
  return (
    <div className={`ink-field ${className ?? ''}`}>
      {label && (
        <label className="ink-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <input
        id={id}
        type="number"
        className="ink-input"
        value={value}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        {...rest}
      />
    </div>
  )
}

interface TextAreaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange'> {
  label?: string
  onChange?: (value: string) => void
  counter?: boolean
}

export function TextArea({ label, onChange, counter, className, maxLength, value, ...rest }: TextAreaProps) {
  const id = useId()
  return (
    <div className={`ink-field ${className ?? ''}`}>
      {label && (
        <label className="ink-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <textarea
        id={id}
        className="ink-textarea"
        maxLength={maxLength}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        {...rest}
      />
      {counter && maxLength && (
        <span className="ink-field-counter">
          {String(value ?? '').length}/{maxLength}
        </span>
      )}
    </div>
  )
}

export interface SelectOption {
  value: string
  label: string
}

interface SelectFieldProps {
  label?: string
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  disabled?: boolean
  className?: string
}

export function SelectField({ label, value, onChange, options, disabled, className }: SelectFieldProps) {
  const id = useId()
  return (
    <div className={`ink-field ${className ?? ''}`}>
      {label && (
        <label className="ink-field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <select id={id} className="ink-select" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export function Switch({
  label,
  checked,
  onChange,
  disabled,
}: {
  label?: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className="ink-switch">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="ink-switch-track" />
      {label && <span>{label}</span>}
    </label>
  )
}

export function Slider({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  label: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  step?: number
}) {
  return (
    <div className="ink-field flex-1" style={{ minWidth: 160 }}>
      <div className="row justify-between items-baseline w-full">
        <span className="ink-field-label">{label}</span>
        <span className="ink-slider-value">{value}</span>
      </div>
      <div className="ink-slider-row">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
    </div>
  )
}

// Free-text multi-value input rendered as removable chips (replaces NiceGUI's
// `ui.select(multiple, new_value_mode="add-unique")`). Enter/comma adds a value.
export function ChipsInput({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string
  values: string[]
  onChange: (values: string[]) => void
  placeholder?: string
}) {
  const [draft, setDraft] = useState('')

  const commit = () => {
    const trimmed = draft.trim()
    if (trimmed && !values.includes(trimmed)) onChange([...values, trimmed])
    setDraft('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      commit()
    } else if (event.key === 'Backspace' && draft === '' && values.length > 0) {
      onChange(values.slice(0, -1))
    }
  }

  return (
    <div className="ink-field">
      <span className="ink-field-label">{label}</span>
      <div className="ink-chips">
        {values.map((value) => (
          <span key={value} className="ink-chip">
            {value}
            <button type="button" aria-label={`Remove ${value}`} onClick={() => onChange(values.filter((v) => v !== value))}>
              ×
            </button>
          </span>
        ))}
        <input
          value={draft}
          placeholder={values.length === 0 ? placeholder : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
        />
      </div>
    </div>
  )
}

export interface RefOption {
  id: string
  name: string
}

// Multi-select over known id/name pairs (e.g. Immich albums) rendered as
// chips with a filtering dropdown. When `options` is undefined (lookup
// unavailable), falls back to free-text ID entry via ChipsInput so the form
// keeps working without the server-side proxy.
export function RefMultiSelect({
  label,
  values,
  onChange,
  options,
  placeholder,
}: {
  label: string
  values: string[]
  onChange: (values: string[]) => void
  options: RefOption[] | undefined
  placeholder?: string
}) {
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)

  if (!options) {
    return <ChipsInput label={label} values={values} onChange={onChange} placeholder={placeholder} />
  }

  const nameById = new Map(options.map((option) => [option.id, option.name]))
  const matches = options
    .filter((option) => !values.includes(option.id))
    .filter((option) => option.name.toLowerCase().includes(draft.toLowerCase()))
    .slice(0, 8)

  return (
    <div className="ink-field" style={{ position: 'relative' }}>
      <span className="ink-field-label">{label}</span>
      <div className="ink-chips">
        {values.map((id) => (
          <span key={id} className="ink-chip">
            {nameById.get(id) ?? id}
            <button type="button" aria-label={`Remove ${nameById.get(id) ?? id}`} onClick={() => onChange(values.filter((v) => v !== id))}>
              ×
            </button>
          </span>
        ))}
        <input
          value={draft}
          placeholder={values.length === 0 ? (placeholder ?? 'Type to search…') : undefined}
          onChange={(e) => {
            setDraft(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      </div>
      {open && matches.length > 0 && (
        <div className="ink-dropdown">
          {matches.map((option) => (
            <button
              key={option.id}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                onChange([...values, option.id])
                setDraft('')
              }}
            >
              {option.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function Expansion({
  title,
  children,
  bordered,
  defaultOpen,
}: {
  title: ReactNode
  children: ReactNode
  bordered?: boolean
  defaultOpen?: boolean
}) {
  return (
    <details className={`ink-expansion ${bordered ? 'bordered' : ''}`} open={defaultOpen}>
      <summary>{title}</summary>
      <div className="ink-expansion-body">{children}</div>
    </details>
  )
}

// Hour/minute pair with a "use default" escape hatch — shared by the device
// schedule dialog, the grid editor, and settings.
export function IntervalInputs({
  hours,
  minutes,
  onHours,
  onMinutes,
  disabled,
}: {
  hours: number | ''
  minutes: number | ''
  onHours: (v: number | '') => void
  onMinutes: (v: number | '') => void
  disabled?: boolean
}) {
  return (
    <div className="row gap-3 w-full">
      <NumberField label="Hours" value={hours} onChange={onHours} min={0} step={1} disabled={disabled} className="flex-1" />
      <NumberField
        label="Minutes"
        value={minutes}
        onChange={onMinutes}
        min={0}
        max={59}
        step={1}
        disabled={disabled}
        className="flex-1"
      />
    </div>
  )
}

export function totalSeconds(hours: number | '', minutes: number | ''): number {
  return (Number(hours) || 0) * 3600 + (Number(minutes) || 0) * 60
}
