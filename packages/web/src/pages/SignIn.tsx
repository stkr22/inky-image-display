// Shown instead of the app when auth is enforced and no session exists.
// A deliberate button rather than an automatic redirect: it can never loop
// if the OIDC callback fails, and guests arriving via invite links skip
// this page entirely (their session is set before the SPA loads).

import { Button } from '../components/fields'
import { useAuth } from '../lib/auth'

export function SignIn() {
  const { signIn } = useAuth()
  return (
    <main className="ink-page" style={{ display: 'grid', placeItems: 'center', minHeight: '80vh' }}>
      <div className="ink-card" style={{ maxWidth: 360, padding: 32, textAlign: 'center' }}>
        <div className="row justify-center items-center" style={{ gap: 8, marginBottom: 8 }}>
          <span className="ink-nav-brand-dot" />
          <span className="ink-h3">Inky / image display</span>
        </div>
        <span className="ink-small">Sign in with your identity provider to manage displays and images.</span>
        <div className="row justify-center" style={{ marginTop: 16 }}>
          <Button primary icon="login" onClick={signIn}>
            Sign in
          </Button>
        </div>
      </div>
    </main>
  )
}
