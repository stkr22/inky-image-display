import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { Button } from './fields'

// Open dialogs, innermost last: a ConfirmDialog opened from inside another
// dialog must take Escape for itself instead of closing both at once.
const openDialogs: symbol[] = []

export function Dialog({
  open,
  onClose,
  children,
  style,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
  style?: CSSProperties
}) {
  // Only a press that both starts and ends on the backdrop closes: a text
  // selection dragged from an input out onto the backdrop fires a click
  // there too, and used to throw away whatever was being typed.
  const pressStartedOnBackdrop = useRef(false)

  useEffect(() => {
    if (!open) return
    const id = Symbol('dialog')
    openDialogs.push(id)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && openDialogs[openDialogs.length - 1] === id) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      openDialogs.splice(openDialogs.indexOf(id), 1)
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="ink-dialog-backdrop"
      onMouseDown={(event) => {
        pressStartedOnBackdrop.current = event.target === event.currentTarget
      }}
      onClick={(event) => {
        event.stopPropagation()
        if (pressStartedOnBackdrop.current && event.target === event.currentTarget) onClose()
        pressStartedOnBackdrop.current = false
      }}
    >
      {/* stopPropagation: dialogs render inline, so clicks inside must not
          reach clickable ancestors (rows, tiles) the dialog was opened from. */}
      <div className="ink-dialog" style={style} role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open,
  message,
  confirmLabel = 'Confirm',
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  message: string
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Dialog open={open} onClose={onCancel}>
      <span className="ink-body">{message}</span>
      <div className="row justify-end gap-2 w-full">
        <Button flat onClick={onCancel}>
          Cancel
        </Button>
        <Button primary={!destructive} danger={destructive} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  )
}
