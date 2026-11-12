import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import { SignIn } from './pages/SignIn'

// Pages are split per route so the first paint only ships the shell and the
// page being opened; the pages are named exports, hence the default-wrapping.
const DisplayJobForm = lazy(() => import('./pages/DisplayJobForm').then((m) => ({ default: m.DisplayJobForm })))
const Displays = lazy(() => import('./pages/Displays').then((m) => ({ default: m.Displays })))
const CalibreJobForm = lazy(() => import('./pages/CalibreJobForm').then((m) => ({ default: m.CalibreJobForm })))
const GeminiJobForm = lazy(() => import('./pages/GeminiJobForm').then((m) => ({ default: m.GeminiJobForm })))
const GenAI = lazy(() => import('./pages/GenAI').then((m) => ({ default: m.GenAI })))
const GridDetail = lazy(() => import('./pages/GridDetail').then((m) => ({ default: m.GridDetail })))
const ImageDetail = lazy(() => import('./pages/ImageDetail').then((m) => ({ default: m.ImageDetail })))
const Images = lazy(() => import('./pages/Images').then((m) => ({ default: m.Images })))
const ImageUpload = lazy(() => import('./pages/ImageUpload').then((m) => ({ default: m.ImageUpload })))
const Jobs = lazy(() => import('./pages/Jobs').then((m) => ({ default: m.Jobs })))
const Landing = lazy(() => import('./pages/Landing').then((m) => ({ default: m.Landing })))
const Settings = lazy(() => import('./pages/Settings').then((m) => ({ default: m.Settings })))
const SyncJobForm = lazy(() => import('./pages/SyncJobForm').then((m) => ({ default: m.SyncJobForm })))

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
        <Route path="/calibre-jobs" element={<Navigate to="/jobs?tab=books" replace />} />
        <Route path="/calibre-jobs/new" element={<CalibreJobForm />} />
        <Route path="/calibre-jobs/:jobId" element={<CalibreJobForm />} />
        <Route path="/display-jobs" element={<Navigate to="/jobs?tab=display" replace />} />
        <Route path="/display-jobs/:jobId" element={<DisplayJobForm />} />
        <Route path="/genai" element={<GenAI />} />
        <Route path="/generate" element={<Navigate to="/genai" replace />} />
        <Route path="/prompts" element={<Navigate to="/genai" replace />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
