import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'

export type ToastType = 'info' | 'positive' | 'negative' | 'warning'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface NotifyOptions {
  action?: ToastAction
  durationMs?: number
}

interface Toast {
  id: number
  message: string
  type: ToastType
  action?: ToastAction
}

type NotifyFn = (message: string, type?: ToastType, options?: NotifyOptions) => void

const ToastContext = createContext<NotifyFn | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(0)

  const notify = useCallback<NotifyFn>((message, type = 'info', options) => {
    const id = nextId.current++
    setToasts((current) => [...current, { id, message, type, action: options?.action }])
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), options?.durationMs ?? 4000)
  }, [])

  const dismiss = (id: number) => setToasts((current) => current.filter((t) => t.id !== id))

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="ink-toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`ink-toast ${toast.type === 'info' ? '' : toast.type}${toast.action ? ' ink-toast-has-action' : ''}`}
          >
            {toast.message}
            {toast.action && (
              <button
                className="ink-toast-action"
                onClick={() => {
                  // Dismiss first so the action can't be triggered twice.
                  dismiss(toast.id)
                  toast.action?.onClick()
                }}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useNotify(): NotifyFn {
  const notify = useContext(ToastContext)
  if (!notify) throw new Error('useNotify must be used inside <ToastProvider>')
  return notify
}
