// Click-driven end-to-end smoke for the NiceGUI app.
//
// Drives the four-section nav (Images, Devices, Jobs, GenAI), toggles the
// Jobs tabs, walks through "New Gemini job" → form → back, and checks the
// GenAI form constraints. Exits non-zero on assertion failure or any browser
// console error.
//
// Targets http://localhost:8080 by default; override with UI_BASE_URL.

const { chromium } = require('playwright');

const TARGET_URL = process.env.UI_BASE_URL || 'http://localhost:8080';

let failed = 0;
function assert(cond, label) {
  if (!cond) {
    console.log(`FAIL: ${label}`);
    failed++;
  } else {
    console.log(`ok    ${label}`);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(`[console] ${msg.text()}`);
  });
  page.on('pageerror', (err) => consoleErrors.push(`[pageerror] ${err.message}`));

  // -- Landing ------------------------------------------------------------
  console.log('\n=== Landing ===');
  await page.goto(`${TARGET_URL}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const navLinks = await page.locator('.ink-nav-link:not(:has-text("→"))').allTextContents();
  assert(
    JSON.stringify(navLinks) === JSON.stringify(['Images', 'Devices', 'Jobs', 'GenAI']),
    `nav is [Images, Devices, Jobs, GenAI] (got ${JSON.stringify(navLinks)})`,
  );
  const bodyText = await page.locator('body').innerText();
  assert(bodyText.includes('Jobs'), 'landing shows Jobs tile');
  assert(!bodyText.includes('AI prompts'), 'landing has no AI prompts tile');
  assert(bodyText.includes('Generate an image'), 'landing has Generate-an-image quick action');
  await page.screenshot({ path: '/tmp/ui-landing.png', fullPage: true });

  // -- /jobs tab switching -----------------------------------------------
  console.log('\n=== /jobs tab switching (5 toggles) ===');
  await page.goto(`${TARGET_URL}/jobs`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  for (let i = 0; i < 5; i++) {
    const target = i % 2 === 0 ? 'Gemini' : 'Immich';
    await page.getByRole('button', { name: target, exact: true }).click();
    await page.waitForTimeout(400);
    const body = await page.locator('body').innerText();
    const expectedEmpty = target === 'Gemini' ? 'No Gemini jobs yet.' : 'No Immich sync jobs yet.';
    assert(body.includes(expectedEmpty), `switch #${i + 1} → ${target}: "${expectedEmpty}"`);
    const newBtn = await page
      .getByRole('button', { name: /New (Immich|Gemini) job/ })
      .innerText();
    assert(newBtn.includes(target), `switch #${i + 1} → ${target}: button reads "New ${target} job"`);
  }
  await page.screenshot({ path: '/tmp/ui-jobs-after-toggles.png', fullPage: true });

  // -- Gemini → New → form → back ----------------------------------------
  console.log('\n=== Gemini → New Gemini job → back ===');
  await page.getByRole('button', { name: 'New Gemini job' }).click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(500);
  assert(page.url().endsWith('/gemini-jobs/new'), `URL = /gemini-jobs/new (got ${page.url()})`);
  const heading = await page.locator('.ink-h2').first().innerText();
  assert(heading.includes('New Gemini job'), `heading "New Gemini job" (got "${heading}")`);

  await page.locator('button:has(i.material-icons:text("arrow_back"))').first().click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(500);
  assert(page.url().includes('/jobs'), `back lands on /jobs (got ${page.url()})`);
  assert(
    (await page.locator('body').innerText()).includes('Gemini'),
    'back lands with Gemini tab content',
  );

  // -- /genai form constraints -------------------------------------------
  console.log('\n=== /genai form ===');
  await page.goto(`${TARGET_URL}/genai`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  const subjectTextarea = page.locator('textarea').first();
  await subjectTextarea.click();
  await subjectTextarea.type('x'.repeat(250));
  const subjectVal = await subjectTextarea.inputValue();
  assert(subjectVal.length === 200, `subject clamped to 200 chars (got ${subjectVal.length})`);

  // Advanced expansion: header visible, library children initially clipped.
  const advancedHeader = await page.getByText('Advanced — prompt library').isVisible();
  assert(advancedHeader, '"Advanced — prompt library" header visible');
  // Quasar collapses children with height: 0; an offsetHeight check is more
  // reliable than visibility because Quasar keeps the DOM mounted.
  const advancedClosedHeight = await page.evaluate(() => {
    const el = document.querySelector('.q-expansion-item__content');
    return el ? el.offsetHeight : -1;
  });
  assert(
    advancedClosedHeight === 0,
    `Advanced library is collapsed by default (height=${advancedClosedHeight})`,
  );
  await page.screenshot({ path: '/tmp/ui-genai.png', fullPage: true });

  // -- Summary -----------------------------------------------------------
  console.log('\n=== Summary ===');
  console.log(`assertions failed: ${failed}`);
  console.log(`console errors:    ${consoleErrors.length}`);
  if (consoleErrors.length) console.log(consoleErrors);

  await browser.close();
  process.exit(failed === 0 && consoleErrors.length === 0 ? 0 : 1);
})();
