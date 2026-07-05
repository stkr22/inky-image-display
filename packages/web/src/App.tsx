import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import { Displays } from './pages/Displays'
import { GeminiJobForm } from './pages/GeminiJobForm'
import { GenAI } from './pages/GenAI'
import { GridDetail } from './pages/GridDetail'
import { ImageDetail } from './pages/ImageDetail'
import { Images } from './pages/Images'
import { ImageUpload } from './pages/ImageUpload'
import { Jobs } from './pages/Jobs'
import { Landing } from './pages/Landing'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { SyncJobForm } from './pages/SyncJobForm'

export function App() {
  const auth = useAuth()

  if (auth.loading) {
    return (
      <main className="ink-page" style={{ display: 'grid', placeItems: 'center', minHeight: '80vh' }}>
        <Spinner />
      </main>
    )
  }
  if (auth.authEnabled && !auth.authenticated) return <SignIn />

  // Guests only get the pages their API allowlist supports (browse images,
  // generate); everything else routes to GenAI instead of surfacing 403s.
  if (auth.role === 'guest') {
    return (
      <Routes>
        <Route element={<Layout />}>
          <Route path="/images" element={<Images />} />
          <Route path="/images/:imageId" element={<ImageDetail />} />
          <Route path="/genai" element={<GenAI />} />
          <Route path="*" element={<Navigate to="/genai" replace />} />
        </Route>
      </Routes>
    )
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/images" element={<Images />} />
        <Route path="/images/new" element={<ImageUpload />} />
        <Route path="/images/:imageId" element={<ImageDetail />} />
        <Route path="/displays" element={<Displays />} />
        <Route path="/grids/:gridId" element={<GridDetail />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/sync-jobs" element={<Navigate to="/jobs" replace />} />
        <Route path="/sync-jobs/new" element={<SyncJobForm />} />
        <Route path="/sync-jobs/:jobId" element={<SyncJobForm />} />
        <Route path="/gemini-jobs" element={<Navigate to="/jobs?tab=gemini" replace />} />
        <Route path="/gemini-jobs/new" element={<GeminiJobForm />} />
        <Route path="/gemini-jobs/:jobId" element={<GeminiJobForm />} />
        <Route path="/genai" element={<GenAI />} />
        <Route path="/generate" element={<Navigate to="/genai" replace />} />
        <Route path="/prompts" element={<Navigate to="/genai" replace />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
