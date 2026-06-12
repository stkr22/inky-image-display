import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
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
import { SyncJobForm } from './pages/SyncJobForm'

export function App() {
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
