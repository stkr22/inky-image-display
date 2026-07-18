// The Immich lookup pickers must fail loudly per field: an API key missing
// e.g. album.read breaks only the albums lookup, and that used to degrade to
// a bare free-text input with no explanation. Routes are stubbed in-browser
// so this runs the same against any backend.

import { expect, test } from '@playwright/test'

const fulfillJson = (status: number, body: unknown) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

test('sync-job form surfaces per-picker Immich lookup failures', async ({ page }) => {
  await page.route('**/api/immich/albums', (route) => route.fulfill(fulfillJson(502, { detail: 'Immich returned 403' })))
  await page.route('**/api/immich/people', (route) => route.fulfill(fulfillJson(502, { detail: 'Immich returned 403' })))
  await page.route('**/api/immich/tags', (route) => route.fulfill(fulfillJson(200, [{ id: 't1', name: 'travel/beach' }])))

  await page.goto('/sync-jobs/new', { waitUntil: 'networkidle' })

  // Albums and People each carry their own error; Tags stays a working picker.
  await expect(page.getByText(/Name lookup failed \(Immich returned 403\)/)).toHaveCount(2)
  await expect(page.getByText(/lacks read access/).first()).toBeVisible()
  await page.getByPlaceholder('Add a tag…').fill('beach')
  await expect(page.getByRole('button', { name: 'travel/beach' })).toBeVisible()

  // The "not configured" note is reserved for the 503 case, not real failures.
  await expect(page.getByText(/proxy not configured/)).toHaveCount(0)
})

test('sync-job form explains non-obvious options with tooltips', async ({ page }) => {
  await page.goto('/sync-jobs/new', { waitUntil: 'networkidle' })

  // Spot-check the least self-explanatory options; each ⓘ carries the full
  // explanation as a native title tooltip.
  await expect(page.getByTitle(/SMART only: pick the images at random/)).toBeVisible()
  await expect(page.getByTitle(/Fetches Count × this many candidates/)).toBeVisible()
  await expect(page.getByTitle(/Cap on the total images this job keeps/)).toBeVisible()
  await expect(page.getByTitle(/behaves like the panel's native landscape shape/)).toBeVisible()
})

test('sync-job form falls back quietly when the proxy is unconfigured', async ({ page }) => {
  for (const path of ['albums', 'people', 'tags']) {
    await page.route(`**/api/immich/${path}`, (route) =>
      route.fulfill(fulfillJson(503, { detail: 'Immich browsing is not configured on the server.' })),
    )
  }

  await page.goto('/sync-jobs/new', { waitUntil: 'networkidle' })

  await expect(page.getByText(/proxy not configured/)).toBeVisible()
  await expect(page.getByText(/Name lookup failed/)).toHaveCount(0)
})
