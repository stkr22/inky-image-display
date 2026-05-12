# Playwright UI smoke tests

End-to-end click-driven checks for the NiceGUI app. They exercise the
consolidated nav (Images, Devices, Jobs, GenAI), the Jobs tab switching, the
back-arrow → tab routing, and the GenAI form constraints.

## Prerequisites

- API running on `http://localhost:8000` (with a seeded device)
- UI running on `http://localhost:8080`
- Playwright with Chromium installed once via the [`playwright-skill`](https://github.com/anthropics/skills) plugin
  (or directly: `npm install playwright && npx playwright install chromium`)

## Running

```bash
# from the skill cache directory
cd ~/.claude/plugins/marketplaces/playwright-skill/skills/playwright-skill
node run.js /workspaces/inky-image-display/integration/playwright/ui_flow.js
```

Or directly with `node` if Playwright is on the node path:

```bash
node integration/playwright/ui_flow.js
```

Override the target with `UI_BASE_URL`:

```bash
UI_BASE_URL=http://staging.example.com node integration/playwright/ui_flow.js
```

## What it covers

`ui_flow.js` runs four blocks of assertions (all click-driven, never
URL-only):

1. **Landing** — confirms the four-item nav, the combined Jobs tile, and that
   the AI-prompts tile and standalone Generate tile no longer exist.
2. **Jobs tabs** — toggles Immich ↔ Gemini five times; the content and the
   "New Immich job" / "New Gemini job" button must follow the active tab.
3. **Form ↔ list navigation** — opens the Gemini create form via the New
   button and confirms the back arrow lands on `/jobs?tab=gemini` (not a
   blank page).
4. **GenAI form** — subject textarea is clamped at 200 characters and the
   "Advanced — prompt library" expansion is closed by default.

Screenshots land in `/tmp/ui-*.png` for visual diffing. Exit code is non-zero
if any assertion fails or any browser console error fires during the run.
