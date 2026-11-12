import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { App } from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { RouteError } from './components/RouteError'
import { notifyFromOutside, ToastProvider } from './components/Toast'
import { ApiError, errMessage } from './lib/api'
import { AuthProvider } from './lib/auth'
import './styles/global.css'

// Polling queries fail on every tick while the API is down; one toast per
// message per window is enough to say so without burying the screen.
const TOAST_DEDUPE_MS = 10_000
const recentToasts = new Map<string, number>()

function toastError(prefix: string, error: unknown) {
  // 401 hands over to the sign-in gate (see api.ts) — not worth a toast.
  if (error instanceof ApiError && error.statusCode === 401) return
  const message = `${prefix}: ${errMessage(error)}`
  const now = Date.now()
  if ((recentToasts.get(message) ?? 0) > now - TOAST_DEDUPE_MS) return
  recentToasts.set(message, now)
  notifyFromOutside(message, 'negative')
}

const queryClient = new QueryClient({
  // Most pages only render data or a spinner; without a global handler a
  // failed fetch was invisible. Queries that expect failures (e.g. the
  // optional Immich proxy answering 503) opt out via meta.silentError.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.meta?.silentError) return
      toastError('Loading failed', error)
    },
  }),
  // Mutations with their own onError already tell the user what failed;
  // this only catches the ones that don't.
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.options.onError) return
      toastError('Request failed', error)
    },
  }),
  defaultOptions: {
    queries: {
      // Lists refresh in the background on navigation; 10s staleness keeps
      // the UI snappy without hammering the API.
      staleTime: 10_000,
      retry: 1,
    },
  },
})

// A data router (instead of <BrowserRouter>) so useBlocker is available for
// unsaved-changes guards; App keeps its own descendant <Routes>. The route's
// errorElement catches render errors (including failed lazy chunk loads)
// and, unlike the outer boundary, resets when the user navigates away.
const router = createBrowserRouter([{ path: '*', element: <App />, errorElement: <RouteError /> }])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <ToastProvider>
            <RouterProvider router={router} />
          </ToastProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
