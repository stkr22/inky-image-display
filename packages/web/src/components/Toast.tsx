import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

export type ToastType = 'info' | 'positive' | 'negative' | 'warning'

interface Toast {
  id: number
  message: string
  type: ToastType
}

type NotifyFn = (message: string, type?: ToastType) => void

const ToastContext = createContext<NotifyFn | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(0)

  const notify = useCallback<NotifyFn>((message, type = 'info') => {
    const id = nextId.current++
    setToasts((current) => [...current, { id, message, type }])
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 4000)
  }, [])

  const value = useMemo(() => notify, [notify])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="ink-toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`ink-toast ${toast.type === 'info' ? '' : toast.type}`}>
            {toast.message}
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
