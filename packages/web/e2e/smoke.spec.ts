// Page-by-page smoke: every section renders its heading with no console
// errors, no failed requests, and no unexpected 4xx/5xx responses.
// Data-independent — passes against an empty or populated library.

import { expect, test } from '@playwright/test'
import { collectProblems } from './helpers'

const SECTIONS: Array<{ path: string; heading: string | RegExp }> = [
  { path: '/', heading: 'Your photos, on paper that never sleeps.' },
  { path: '/images', heading: 'Images' },
  { path: '/images/new', heading: 'Upload image' },
  { path: '/jobs', heading: 'Jobs' },
  { path: '/jobs?tab=books', heading: 'Jobs' },
  { path: '/sync-jobs/new', heading: 'New sync job' },
  { path: '/gemini-jobs/new', heading: 'New Gemini job' },
  { path: '/calibre-jobs/new', heading: 'New bookshelf job' },
  { path: '/genai', heading: 'Generate an image' },
  { path: '/genai?tab=prompts', heading: 'Prompt library' },
  { path: '/settings', heading: 'Settings' },
]

for (const section of SECTIONS) {
  test(`renders ${section.path} cleanly`, async ({ page }) => {
    const problems = collectProblems(page)
    await page.goto(section.path, { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { name: section.heading }).first()).toBeVisible()
    expect(problems.consoleErrors).toEqual([])
    expect(problems.badResponses).toEqual([])
  })
}

test('renders /displays with all three sections', async ({ page }) => {
  const problems = collectProblems(page)
  await page.goto('/displays', { waitUntil: 'networkidle' })
  for (const heading of ['Schedule', 'Devices', 'Grids']) {
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  }
  expect(problems.consoleErrors).toEqual([])
  expect(problems.badResponses).toEqual([])
})

test('legacy routes redirect to their new homes', async ({ page }) => {
  await page.goto('/prompts')
  await expect(page).toHaveURL(/\/genai$/)
  await page.goto('/generate')
  await expect(page).toHaveURL(/\/genai$/)
  await page.goto('/sync-jobs')
  await expect(page).toHaveURL(/\/jobs$/)
  await page.goto('/gemini-jobs')
  await expect(page).toHaveURL(/\/jobs\?tab=gemini$/)
  // The MOTD/display-jobs GenAI tab moved into the Jobs page.
  await page.goto('/genai?tab=jobs')
  await expect(page).toHaveURL(/\/jobs\?tab=display$/)
  await page.goto('/display-jobs')
  await expect(page).toHaveURL(/\/jobs\?tab=display$/)
  await page.goto('/calibre-jobs')
  await expect(page).toHaveURL(/\/jobs\?tab=books$/)
})

test('display jobs tab creates a job and opens its editor', async ({ page }) => {
  const problems = collectProblems(page)
  const name = `e2e display job ${Date.now()}`
  await page.goto('/jobs?tab=display', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'New display job' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name').fill(name)
  await dialog.getByRole('button', { name: 'Create' }).click()

  await expect(page).toHaveURL(/\/display-jobs\/[0-9a-f-]+$/)
  const jobId = page.url().split('/').pop()!
  try {
    await expect(page.getByRole('heading', { name })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save configuration' })).toBeVisible()

    // Back on the list (client-side, so no in-flight request is aborted),
    // the row's edit button leads to the same editor.
    await page.getByRole('link', { name: '← All jobs' }).click()
    await page.waitForLoadState('networkidle')
    const row = page.locator('.bento-tile', { has: page.getByRole('heading', { name }) })
    await row.getByTitle('Edit', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/display-jobs/${jobId}$`))
    await expect(page.getByRole('heading', { name })).toBeVisible()
    expect(problems.consoleErrors).toEqual([])
    expect(problems.badResponses).toEqual([])
  } finally {
    await page.request.delete(`/api/display-jobs/${jobId}`)
  }
})

test('jobs tab state lives in the URL', async ({ page }) => {
  await page.goto('/jobs', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Gemini' }).click()
  await expect(page).toHaveURL(/tab=gemini/)
  await expect(page.getByRole('button', { name: 'New Gemini job' })).toBeVisible()
})

test('dark mode toggles and persists across reloads', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  const html = page.locator('html')
  const initial = await html.getAttribute('data-theme')
  await page.getByRole('button', { name: /switch to (dark|light) mode/i }).click()
  const toggled = await html.getAttribute('data-theme')
  expect(toggled).not.toBe(initial)
  await page.reload({ waitUntil: 'networkidle' })
  await expect(html).toHaveAttribute('data-theme', toggled!)
})
