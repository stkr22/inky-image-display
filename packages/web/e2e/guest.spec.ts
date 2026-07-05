// Guest invite flow: an admin mints an invite link (QR dialog on Settings),
// a fresh browser context opening it becomes a guest with a reduced UI, and
// signing out drops back to the anonymous state. Runs against a stack with
// auth disabled (the default), where guest sessions still restrict access.

import { expect, test, type BrowserContext } from '@playwright/test'
import { collectProblems } from './helpers'

test('guest invite link mints a restricted session', async ({ page, browser }) => {
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
