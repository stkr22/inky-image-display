// Router-level error screen. It lives inside the router (unlike the outer
// ErrorBoundary), so React Router clears it on the next navigation instead of
// leaving the app stuck until a hard reload.

import { Link, useRouteError } from 'react-router-dom'

// After a redeploy the hashed chunk names change; a tab still running the
// old bundle then fails to lazy-load a page. Only a reload fixes that.
const STALE_CHUNK_PATTERNS = [
  'Failed to fetch dynamically imported module',
  'Importing a module script failed',
  'error loading dynamically imported module',
]

export function RouteError() {
  const error = useRouteError()
  const message = error instanceof Error ? error.message : String(error ?? '')
  const staleChunk = STALE_CHUNK_PATTERNS.some((pattern) => message.includes(pattern))

  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', padding: 24 }}>
      <title>Error · Inky</title>
      <div className="ink-card" style={{ maxWidth: 480, padding: 24, textAlign: 'center' }}>
        <h2 className="ink-h3">{staleChunk ? 'A new version is available' : 'Something went wrong'}</h2>
        <p className="ink-small" style={{ wordBreak: 'break-word' }}>
          {staleChunk
            ? 'The app was updated since this tab was opened. Reload to load the new version.'
            : message || 'Unexpected rendering error.'}
        </p>
        <div className="row gap-2" style={{ justifyContent: 'center' }}>
          <button className="ink-btn ink-btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          {!staleChunk && (
            <Link to="/" className="ink-btn ink-btn-flat">
              Back to start
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}
