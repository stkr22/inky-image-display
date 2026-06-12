// End-to-end crop + upload: generate an image in-browser, crop it to the
// first panel preset, upload, verify it landed (gallery + API), then clean
// up via the API so the test leaves no residue.

import { expect, test } from '@playwright/test'
import { collectProblems, makeTestJpeg } from './helpers'

test('crop to a panel preset, upload, and verify exact dimensions', async ({ page, request }) => {
  const problems = collectProblems(page)
  const title = `e2e-crop-${Date.now()}`

  await page.goto('/images/new', { waitUntil: 'networkidle' })

  // Pick a generated 2400x1400 JPEG; orientation auto-detects to landscape.
  const buffer = await makeTestJpeg(page, 2400, 1400)
  await page.setInputFiles('input[type=file]', { name: `${title}.jpg`, mimeType: 'image/jpeg', buffer })
  await expect(page.getByText('2400x1400 px')).toBeVisible()

  // Crop with the first preset (a panel preset when no grid is selected),
  // which forces the panel's exact output dimensions.
  await page.getByRole('button', { name: 'Crop…' }).click()
  const presetLabel = await page.locator('.ink-dialog select option:checked').textContent()
  const dims = presetLabel?.match(/\((\d+)x(\d+)\)/)
  expect(dims).not.toBeNull()
  const [expectedW, expectedH] = [Number(dims![1]), Number(dims![2])]
  await page.getByRole('button', { name: 'Apply crop' }).click()
  await expect(page.getByText(`Cropped to ${expectedW}x${expectedH} px`)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reset to original' })).toBeVisible()

  // Title was prefilled from the filename; upload and land in the gallery.
  await expect(page.getByLabel('Title')).toHaveValue(title)
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  await page.waitForURL(/\/images$/)

  // The API recorded the cropped dimensions exactly.
  const listed = await request.get(`/api/images?search=${title}`)
  expect(listed.ok()).toBeTruthy()
  const rows = await listed.json()
  expect(rows).toHaveLength(1)
  expect(rows[0].original_width).toBe(expectedW)
  expect(rows[0].original_height).toBe(expectedH)
  expect(rows[0].is_portrait).toBe(expectedH > expectedW)

  // Thumbnail variant is generated on demand.
  const thumb = await request.get(`/media/${rows[0].storage_path}?w=240`)
  expect(thumb.ok()).toBeTruthy()
  expect(thumb.headers()['content-type']).toBe('image/jpeg')

  // Clean up so reruns stay deterministic.
  const deleted = await request.delete(`/api/images/${rows[0].id}`)
  expect(deleted.status()).toBe(204)

  expect(problems.consoleErrors).toEqual([])
  expect(problems.badResponses).toEqual([])
})

test('gallery search finds by title', async ({ page, request }) => {
  // Seed one image straight through the API, search for it in the UI.
  const title = `e2e-search-${Date.now()}`
  await page.goto('/images', { waitUntil: 'networkidle' })
  const buffer = await makeTestJpeg(page, 640, 400)
  const created = await request.post('/api/images', {
    multipart: {
      file: { name: `${title}.jpg`, mimeType: 'image/jpeg', buffer },
      metadata: JSON.stringify({ source_name: 'manual', title }),
    },
  })
  expect(created.status()).toBe(201)
  const image = await created.json()

  try {
    await page.getByLabel('Search').fill(title)
    // Debounced search → exactly this image remains.
    await expect(page.locator('.ink-thumb')).toHaveCount(1)
    await expect(page.locator('.ink-thumb-caption')).toHaveText(title)
  } finally {
    await request.delete(`/api/images/${image.id}`)
  }
})
