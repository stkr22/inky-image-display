import { defineConfig } from '@playwright/test'

// E2E tests run against an already-running stack (API serving the built
// frontend, with Garage/Mosquitto reachable — the devcontainer provides
// these). Start it with:
//   npm run build
//   API_DEVICE_MQTT_HOST=mosquitto API_WEB_DIST_PATH=$PWD/dist \
//     uv run inky-image-display-api
// Point WEB_E2E_BASE_URL elsewhere to test a deployed instance.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.WEB_E2E_BASE_URL ?? 'http://localhost:8000',
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure',
  },
})
