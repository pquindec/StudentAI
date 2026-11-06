import { type Page } from '@playwright/test'
import { expect, seed, test } from './fixtures.ts'

// La «nube» del backend de pruebas es un puerto local cerrado (tests/e2e_server.py):
// «Enviar a Claude» nunca llega a Internet; el envío falla y el trabajo sigue en local.

const go = (page: Page, section: string) =>
  page.getByRole('navigation').getByRole('button', { name: section, exact: true }).click()

interface Doc {
  id: string
  status: string
}

async function askSummary(page: Page) {
  await go(page, 'Resúmenes')
  await page.getByRole('button', { name: 'Generar resumen' }).click()
  const dialog = page.getByRole('dialog', { name: 'Generar resumen' })
  await dialog.getByRole('checkbox', { name: /Tema 1/ }).check()
  await dialog.getByRole('button', { name: 'Generar' }).click()
}

async function enableClaude(page: Page) {
  await go(page, 'Configuración')
  // Casilla controlada por el backend: cambia cuando él confirma el ajuste.
  const enabled = page.getByRole('checkbox', { name: /Usar Claude cuando yo lo apruebe/ })
  await enabled.click()
  await expect(enabled).toBeChecked()
  await page.getByRole('textbox', { name: 'sk-ant-…' }).fill('sk-ant-pruebas-0000000000001234')
  await page.getByRole('button', { name: 'Guardar en el llavero' }).click()
  await expect(page.getByText('Guardada en el llavero de macOS (…1234)')).toBeVisible()
}

test('sin activar Claude no se pregunta ni se envía nada', async ({ page, backend }) => {
  const sid = await seed(backend)
  await page.goto('/')
  await askSummary(page)
  await expect(page.getByRole('heading', { name: 'Resumen · Tema 1' })).toBeVisible()
  await expect(page.getByRole('dialog', { name: '¿Enviar a Claude?' })).toHaveCount(0)
  const docs = await backend.api<Doc[]>('GET', `/subjects/${sid}/documents`)
  expect(docs).toHaveLength(1)
  expect(await backend.api<unknown[]>('GET', '/cloud/requests')).toEqual([])
})

test('consentimiento: cancelar, hacerlo en local y enviar', async ({ page, backend }) => {
  const sid = await seed(backend)
  await page.goto('/')
  await enableClaude(page)

  // 1) La ventana muestra qué saldría y el texto exacto; «Cancelar» no crea nada.
  await askSummary(page)
  const consent = page.getByRole('dialog', { name: '¿Enviar a Claude?' })
  await expect(consent).toBeVisible()
  await expect(consent.getByRole('listitem').filter({ hasText: 'Tema 1' })).toBeVisible()
  await expect(consent.getByText(/Coste estimado/)).toBeVisible()
  await consent.getByText('Ver el texto exacto que se enviará').click()
  await expect(consent.getByText(/Párrafo 0: la arquitectura/)).toBeVisible()
  await consent.getByRole('button', { name: 'Cancelar' }).click()
  await expect(consent).toBeHidden()
  expect(await backend.api<Doc[]>('GET', `/subjects/${sid}/documents`)).toHaveLength(0)

  // 2) «Hacerlo en local»: se genera sin enviar nada.
  await page.keyboard.press('Escape')
  await askSummary(page)
  await consent.getByRole('button', { name: 'Hacerlo en local' }).click()
  await expect(page.getByRole('heading', { name: 'Resumen · Tema 1' })).toBeVisible()
  expect(await backend.api<unknown[]>('GET', '/cloud/requests')).toEqual([])

  // 3) «Enviar a Claude» para la sesión: el envío falla (sin conexión) y sigue en local.
  await askSummary(page)
  await consent.getByRole('checkbox', { name: /No volver a preguntar/ }).check()
  await consent.getByRole('button', { name: 'Enviar a Claude' }).click()
  await expect(page.getByRole('heading', { name: 'Resumen · Tema 1' })).toBeVisible()
  await expect
    .poll(async () =>
      (await backend.api<Doc[]>('GET', `/subjects/${sid}/documents`)).map((d) => d.status),
    )
    .toEqual(['ready', 'ready'])
  const audit = await backend.api<{ status: string; chars_sent: number }[]>(
    'GET',
    '/cloud/requests',
  )
  expect(audit.length).toBeGreaterThan(0)
  expect(audit.every((r) => r.status === 'failed')).toBe(true)

  // 4) Aprobado para la sesión: no vuelve a preguntar; se puede revocar en Configuración.
  await askSummary(page)
  await expect(page.getByRole('heading', { name: 'Resumen · Tema 1' })).toBeVisible()
  await expect(consent).toHaveCount(0)
  await go(page, 'Configuración')
  await expect(page.getByRole('cell', { name: 'Falló' }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Revocar todo' }).click()
  await askSummary(page)
  await expect(consent).toBeVisible()
})
