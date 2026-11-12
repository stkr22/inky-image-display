// Guest invite flow: an admin mints an invite link (QR dialog on Settings),
// a fresh browser context opening it becomes a guest with a reduced UI, and
// signing out drops back to the anonymous state. Runs against a stack with
// auth disabled (the default), where guest sessions still restrict access.

import { expect, test, type BrowserContext } from '@playwright/test'
import { collectProblems, makeTestJpeg } from './helpers'

test('guest invite link mints a restricted session', async ({ page, browser, request }) => {
  const problems = collectProblems(page)
  await page.goto('/settings', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Create invite link' }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Guest invite' })).toBeVisible()
  await expect(dialog.getByAltText('Guest invite QR code')).toBeVisible()
  const inviteUrl = await dialog.locator('.ink-small').first().textContent()
  expect(inviteUrl).toContain('/auth/guest?token=')
  expect(problems.consoleErrors).toEqual([])
  expect(problems.badResponses).toEqual([])

  // Fresh context = the guest's phone: no cookies shared with the admin.
  const guestContext: BrowserContext = await browser.newContext()
  const guestPage = await guestContext.newPage()
  await guestPage.goto(inviteUrl!, { waitUntil: 'networkidle' })

  // Guests land on GenAI and only see the pages their role permits.
  await expect(guestPage).toHaveURL(/\/genai$/)
  await expect(guestPage.getByText('Guest', { exact: true })).toBeVisible()
  const nav = guestPage.locator('.ink-nav-links')
  await expect(nav.getByRole('link', { name: 'Images' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Settings' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Displays' })).toHaveCount(0)

  // Every guest page must stay inside the API's guest allowlist: any admin
  // endpoint the UI still calls shows up here as a 403.
  const guestProblems = collectProblems(guestPage)
  await guestPage.goto('/genai', { waitUntil: 'networkidle' })
  await expect(guestPage.getByRole('heading', { name: 'Generate an image' })).toBeVisible()
  await expect(guestPage.getByRole('button', { name: 'Prompt library' })).toHaveCount(0)
  await guestPage.goto('/images', { waitUntil: 'networkidle' })
  await expect(guestPage.getByRole('heading', { name: 'Images' })).toBeVisible()
  await expect(guestPage.getByRole('button', { name: 'Select' })).toHaveCount(0)
  await expect(guestPage.getByTitle('Upload image')).toHaveCount(0)
  // Seed our own image rather than clicking whatever the gallery shows first,
  // so the detail-page check never depends on (or races) other specs' data.
  const created = await request.post('/api/images', {
    multipart: {
      file: { name: 'e2e-guest.jpg', mimeType: 'image/jpeg', buffer: await makeTestJpeg(page, 640, 400) },
      metadata: JSON.stringify({ source_name: 'manual', title: `e2e-guest-${Date.now()}` }),
    },
  })
  expect(created.status()).toBe(201)
  const image = await created.json()
  try {
    await guestPage.goto(`/images/${image.id}`, { waitUntil: 'networkidle' })
    await expect(guestPage.getByRole('button', { name: 'Send to…' })).toBeVisible()
    await expect(guestPage.getByRole('button', { name: 'Save' })).toHaveCount(0)
    await expect(guestPage.getByRole('button', { name: 'Delete' })).toHaveCount(0)
    await guestPage.getByRole('button', { name: 'Send to…' }).click()
    await guestPage.waitForLoadState('networkidle')
    await expect(guestPage.getByRole('dialog').getByText('Grids', { exact: true })).toHaveCount(0)
    await guestPage.keyboard.press('Escape')
  } finally {
    await request.delete(`/api/images/${image.id}`)
  }
  expect(guestProblems.consoleErrors).toEqual([])
  expect(guestProblems.badResponses).toEqual([])

  // Admin-only routes bounce back to GenAI client-side.
  await guestPage.goto('/settings')
  await expect(guestPage).toHaveURL(/\/genai$/)

  // Sign out clears the guest session; with auth disabled the app returns
  // to the full anonymous (trusted-LAN) UI.
  await guestPage.getByRole('button', { name: 'Sign out' }).click()
  await guestPage.waitForURL('/')
  await expect(guestPage.locator('.ink-nav-links').getByRole('link', { name: 'Settings' })).toBeVisible()
  await guestContext.close()
})

test('an expired or bogus invite token is rejected', async ({ page }) => {
  const response = await page.goto('/auth/guest?token=bogus')
  expect(response!.status()).toBe(403)
  await expect(page.getByText('This invite link is invalid or has expired')).toBeVisible()
})
