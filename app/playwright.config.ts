import { defineConfig, devices } from '@playwright/test'

/**
 * Pruebas E2E de la interfaz (Fase 9) en WebKit, el motor del WKWebView de la app.
 * La UI corre en Vite y cada prueba arranca su propio backend (modelos falsos, carpeta temporal);
 * ver `e2e/fixtures.ts`. Nunca usa los datos del usuario.
 */
const PORT = 1430 // distinto de 1420 (`tauri dev`)

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  workers: 3,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: {
    ...devices['Desktop Safari'],
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 1280, height: 860 },
    locale: 'es-ES',
    trace: 'retain-on-failure',
  },
  outputDir: 'node_modules/.e2e-results',
  webServer: {
    command: `npx vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
  },
})
