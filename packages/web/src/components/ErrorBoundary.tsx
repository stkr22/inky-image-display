// Global error boundary: without it a single render error blanks the whole
// SPA with no way back short of knowing to hard-reload.

import { Component, type ReactNode } from 'react'

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error === null) return this.props.children
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', padding: 24 }}>
        <div className="ink-card" style={{ maxWidth: 480, padding: 24, textAlign: 'center' }}>
          <h2 className="ink-h3">Something went wrong</h2>
          <p className="ink-small" style={{ wordBreak: 'break-word' }}>
            {this.state.error.message || 'Unexpected rendering error.'}
          </p>
          <button className="ink-btn ink-btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
