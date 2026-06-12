import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Dev-server proxies mirror the production topology: the API service owns
// both /api and the /media image proxy, so the browser app only ever talks
// same-origin and needs no CORS setup.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.WEB_API_PROXY ?? 'http://localhost:8000'
  const mediaTarget = env.WEB_MEDIA_PROXY ?? apiTarget
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/media': { target: mediaTarget, changeOrigin: true },
      },
    },
  }
})
