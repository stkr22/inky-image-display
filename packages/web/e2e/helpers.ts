import type { Page } from '@playwright/test'

export interface PageProblems {
  consoleErrors: string[]
  badResponses: string[]
}

// 503s from optional integrations are expected when the server runs without
// Gemini / Immich configured — the UI degrades gracefully by design.
const EXPECTED_503_PATHS = ['/api/immich/', '/api/genai/generate']

export function collectProblems(page: Page): PageProblems {
  const problems: PageProblems = { consoleErrors: [], badResponses: [] }
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    // Resource-load 503 errors are reported separately via responses.
    if (msg.text().includes('503 (Service Unavailable)')) return
    problems.consoleErrors.push(`${page.url()}: ${msg.text().slice(0, 300)}`)
  })
  page.on('response', (response) => {
    if (response.status() < 400) return
    const url = new URL(response.url())
    if (response.status() === 503 && EXPECTED_503_PATHS.some((p) => url.pathname.startsWith(p))) return
    problems.badResponses.push(`HTTP ${response.status()} ${url.pathname}`)
  })
  page.on('requestfailed', (request) => {
    problems.badResponses.push(`request failed: ${request.url().slice(0, 160)} ${request.failure()?.errorText ?? ''}`)
  })
  return problems
}

// Generate a JPEG in-page via canvas so tests need no fixture files.
export async function makeTestJpeg(page: Page, width: number, height: number): Promise<Buffer> {
  const bytes = await page.evaluate(
    async ({ w, h }) => {
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')!
      const gradient = ctx.createLinearGradient(0, 0, w, h)
      gradient.addColorStop(0, '#3D5AFE')
      gradient.addColorStop(1, '#F59E0B')
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, w, h)
      const blob: Blob = await new Promise((resolve) => canvas.toBlob((b) => resolve(b!), 'image/jpeg', 0.9))
      return Array.from(new Uint8Array(await blob.arrayBuffer()))
    },
    { w: width, h: height },
  )
  return Buffer.from(bytes)
}
