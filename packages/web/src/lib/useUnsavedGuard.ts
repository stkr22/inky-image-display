// Guard against silently losing form edits: blocks in-app navigation via the
// data router's blocker and tab close/reload via beforeunload.
//
// The blocker predicate reads refs, not render-time booleans: a page that
// saves and then navigates in the same handler would otherwise still be
// "dirty" at navigation time (state updates haven't re-rendered yet) and
// block its own success redirect. Callers invoke the returned `allowLeave`
// right before such programmatic navigation.

import { useCallback, useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'

const DEFAULT_MESSAGE = 'You have unsaved changes — leave anyway?'

export function useUnsavedGuard(dirty: boolean, message: string = DEFAULT_MESSAGE): () => void {
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty
  const bypassRef = useRef(false)

  const blocker = useBlocker(useCallback(() => dirtyRef.current && !bypassRef.current, []))

  useEffect(() => {
    if (blocker.state !== 'blocked') return
    // Native confirm keeps the guard dependency-free; the styled dialogs
    // are per-page and this must work from any form.
    if (window.confirm(message)) blocker.proceed()
    else blocker.reset()
  }, [blocker, message])

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => {
      if (!bypassRef.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  return useCallback(() => {
    bypassRef.current = true
  }, [])
}
