// Session state for the whole app, sourced from GET /api/auth/me (public).
// The API is a backend-for-frontend: the browser never sees tokens, only an
// HttpOnly session cookie, so "auth state" here is just what /me reports.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { api } from './api'

export interface AuthState {
  loading: boolean
  authEnabled: boolean
  authenticated: boolean
  // Effective role: 'admin' covers the trusted-LAN mode (auth disabled),
  // null means locked out (sign-in gate takes over).
  role: 'admin' | 'guest' | null
  name: string | null
  signIn: () => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const { data, isPending } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: api.getAuthMe,
    staleTime: 60_000,
    retry: 1,
  })

  // Any API call answering 401 (expired session) re-checks /me so the
  // sign-in gate appears without a manual refresh.
  useEffect(() => {
    const onUnauthorized = () => queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
    window.addEventListener('inky:unauthorized', onUnauthorized)
    return () => window.removeEventListener('inky:unauthorized', onUnauthorized)
  }, [queryClient])

  const value: AuthState = {
    loading: isPending,
    authEnabled: data?.auth_enabled ?? false,
    authenticated: data?.authenticated ?? false,
    role: data?.role ?? null,
    name: data?.name ?? null,
    // Full-page navigations: sign-in is an OIDC redirect dance, sign-out
    // reloads so all cached queries drop with the session.
    signIn: () => {
      window.location.href = '/auth/login'
    },
    signOut: async () => {
      await api.logout()
      window.location.href = '/'
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext)
  if (!state) throw new Error('useAuth must be used inside AuthProvider')
  return state
}
