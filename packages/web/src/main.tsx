import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { App } from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ToastProvider } from './components/Toast'
import { AuthProvider } from './lib/auth'
import './styles/global.css'

const queryClient = new QueryClient({
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
// unsaved-changes guards; App keeps its own descendant <Routes>.
const router = createBrowserRouter([{ path: '*', element: <App /> }])

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
