import { useEffect, type CSSProperties, type ReactNode } from 'react'
import { Button } from './fields'

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
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="ink-dialog-backdrop" onClick={onClose}>
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
