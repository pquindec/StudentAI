import { devices, type Browser, type Page } from '@playwright/test'
import { expect, seed, test } from './fixtures.ts'

// Examen en vivo (Fase 9.5): el profesor usa la app y los participantes, el navegador de su
// teléfono. Aquí los «teléfonos» son navegadores WebKit con el tamaño y el User-Agent de un
// iPhone o un Android, en 127.0.0.1 (tests/e2e_server.py): nada se abre en la Wi-Fi real.

const go = (page: Page, section: string) =>
  page.getByRole('navigation').getByRole('button', { name: section, exact: true }).click()

interface Exam {
  id: string
  title: string
  status: string
}

async function phone(browser: Browser, device: string, url: string, name: string) {
  const ctx = await browser.newContext({ ...devices[device] })
  const p = await ctx.newPage()
  p.on('dialog', (d) => void d.accept()) // «¿Entregar el examen?»
  await p.goto(url)
  await p.getByRole('textbox', { name: 'Tu nombre' }).fill(name)
  await p.getByRole('button', { name: 'Entrar' }).click()
  return p
}

test('sala en vivo: QR, admitir, iniciar, responder, entregar y publicar', async ({
  page,
  browser,
  backend,
}) => {
  test.setTimeout(90_000)
  const sid = await seed(backend)
  const created = await backend.api<Exam>('POST', `/subjects/${sid}/exams`, {
    config: { count: 3, types: ['single', 'true_false', 'short'] },
  })
  await expect
    .poll(async () => (await backend.api<Exam>('GET', `/exams/${created.id}`)).status, {
      timeout: 30_000,
    })
    .toBe('ready')

  // El profesor abre la sala «con nota» desde el examen.
  await page.goto('/')
  await go(page, 'Exámenes')
  await page.getByRole('button', { name: new RegExp(created.title) }).click()
  await page.getByRole('button', { name: 'Compartir en vivo' }).click()
  const dialog = page.getByRole('dialog', { name: 'Compartir el examen en vivo' })
  await dialog.getByRole('radio', { name: /Con nota/ }).check()
  await dialog.getByRole('button', { name: 'Abrir sala' }).click()
  await expect(page.getByRole('img', { name: 'Escanea para entrar' })).toBeVisible()
  const url = (await page.locator('code').first().textContent()) ?? ''
  expect(url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/s\/[A-Z2-9]{8}\/$/)

  // Acceso por internet (Cloudflare, falso en las pruebas): pide consentimiento y cambia el QR.
  await page.getByRole('button', { name: 'Compartir por internet' }).click()
  const consent = page.getByRole('dialog', { name: 'Compartir la sala por internet' })
  await expect(consent.getByText(/Cloudflare podrá ver lo que circula/)).toBeVisible()
  await consent.getByRole('button', { name: 'Compartir por internet' }).click()
  await expect(page.getByText(/Compartida por internet con Cloudflare/)).toBeVisible()
  await expect(page.locator('code').first()).toHaveText(
    /^https:\/\/sala-de-pruebas-e2e\.trycloudflare\.com\/s\/[A-Z2-9]{8}\/$/,
  )
  await page.getByRole('button', { name: 'Dejar de compartir por internet' }).click()
  await expect(page.locator('code').first()).toHaveText(url)

  // Solo en la app: preguntas con la respuesta correcta y la fuente (cerradas por defecto).
  await expect(page.getByText('Por qué:')).toHaveCount(0)
  await page.getByRole('button', { name: 'Mostrar' }).click()
  await expect(page.getByText('Por qué:')).toHaveCount(3)
  await expect(page.getByText('Evidencia en tus fuentes')).toHaveCount(3)
  await expect(page.getByText(/^✓ /)).toHaveCount(1)
  await page.getByRole('button', { name: 'Ocultar' }).click()

  // Tres teléfonos entran y esperan a que los admita.
  const phones = await Promise.all([
    phone(browser, 'iPhone 15', url, 'Ana Pérez'),
    phone(browser, 'Pixel 7', url, 'Luis Gómez'),
    phone(browser, 'iPhone 15', url, 'Marta Ruiz'),
  ])
  for (const p of phones)
    await expect(p.getByText('Esperando a que el profesor te admita…')).toBeVisible()
  await expect(page.getByText('Participantes (3)')).toBeVisible()
  await expect(page.getByText('Android · Chrome')).toBeVisible()
  const admit = page.getByRole('button', { name: 'Admitir' })
  await expect(page.getByRole('button', { name: 'Iniciar examen' })).toBeDisabled()
  for (let i = 0; i < 3; i++) {
    await admit.first().click()
    await expect(admit).toHaveCount(2 - i)
  }
  for (const p of phones)
    await expect(p.getByText('Esperando a que empiece el examen…')).toBeVisible()

  // Empieza para todos a la vez.
  await page.getByRole('button', { name: 'Iniciar examen' }).click()
  for (const p of phones) {
    await expect(p.getByText('Pregunta 1 de 3')).toBeVisible()
    for (const group of await p.getByRole('radiogroup').all()) {
      await group.getByRole('radio').first().check()
    }
    await p.getByRole('textbox').fill('Las capas se comunican mediante protocolos.')
    await p.getByRole('textbox').blur()
    await expect(p.getByText('Guardado ✓')).toHaveCount(3)
  }
  await expect(page.getByText('Respondiendo · 3/3')).toHaveCount(3)

  // Si el teléfono recarga (o se bloquea), vuelve con sus respuestas.
  await phones[0].reload()
  await expect(phones[0].getByRole('radio', { checked: true })).toHaveCount(2)
  await expect(phones[0].getByRole('textbox')).toHaveValue(/protocolos/)

  for (const p of phones) {
    await p.getByRole('button', { name: 'Entregar examen' }).click()
    await expect(p.getByText('Examen entregado ✓')).toBeVisible()
    await expect(p.getByText('El profesor publicará las notas.')).toBeVisible()
  }

  // Terminar, revisar y publicar.
  await page.getByRole('button', { name: 'Terminar examen' }).click()
  await page
    .getByRole('dialog', { name: 'Terminar examen' })
    .getByRole('button', { name: 'Terminar examen' })
    .click()
  await expect(page.getByRole('heading', { name: 'Resultados' })).toBeVisible()
  await expect(page.getByText(/\/10/).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Publicar notas' }).click()
  await expect(page.getByText('Notas publicadas: los participantes ya las ven.')).toBeVisible()
  for (const p of phones) await expect(p.getByText('Tu nota')).toBeVisible({ timeout: 15_000 })

  // Cerrar: sin salas abiertas el servidor de la sala se apaga (la conexión se rechaza).
  await page.getByRole('button', { name: 'Cerrar sala' }).click()
  await page
    .getByRole('dialog', { name: 'Cerrar sala' })
    .getByRole('button', { name: 'Cerrar sala' })
    .click()
  await expect(page.getByText(/Sala cerrada/).first()).toBeVisible()
  const gone = await phones[1].request.get(url + 'state').then(
    (r) => r.status(),
    () => 'refused',
  )
  expect(gone).toBe('refused')
  for (const p of phones) await p.context().close()
})

test('concurso: proyector, 3 teléfonos, clasificación y podio', async ({
  page,
  browser,
  backend,
}) => {
  test.setTimeout(90_000)
  const sid = await seed(backend)
  const created = await backend.api<Exam>('POST', `/subjects/${sid}/exams`, {
    config: { count: 3, types: ['single', 'true_false', 'short'] },
  })
  await expect
    .poll(async () => (await backend.api<Exam>('GET', `/exams/${created.id}`)).status, {
      timeout: 30_000,
    })
    .toBe('ready')

  await page.goto('/')
  await go(page, 'Exámenes')
  await page.getByRole('button', { name: new RegExp(created.title) }).click()
  await page.getByRole('button', { name: 'Compartir en vivo' }).click()
  const dialog = page.getByRole('dialog', { name: 'Compartir el examen en vivo' })
  await dialog.getByRole('radio', { name: /Concurso/ }).check()
  await expect(dialog.getByRole('spinbutton')).toHaveCount(0) // sin tiempo total
  await dialog.getByRole('combobox', { name: 'Segundos por pregunta' }).selectOption('10')
  await dialog.getByRole('button', { name: 'Abrir sala' }).click()
  await expect(page.getByText(/1 pregunta de respuesta corta no entra/)).toBeVisible()
  const url = (await page.locator('code').first().textContent()) ?? ''

  // Entran con un apodo (se avisa de que se proyectará).
  const join = async (device: string, name: string) => {
    const ctx = await browser.newContext({ ...devices[device] })
    const p = await ctx.newPage()
    await p.goto(url)
    await expect(p.getByText(/Se mostrará en la clasificación/)).toBeVisible()
    await p.getByRole('textbox', { name: 'Tu nombre o apodo' }).fill(name)
    await p.getByRole('button', { name: 'Entrar' }).click()
    await expect(p.getByText('Esperando a que empiece el concurso…')).toBeVisible()
    return p
  }
  const phones = [
    await join('iPhone 15', 'Rayo'),
    await join('Pixel 7', 'Luna'),
    await join('iPhone 15', 'Cometa'),
  ]

  // Proyector: QR y quién ha entrado.
  await page.getByRole('button', { name: 'Proyectar' }).click()
  const screen = page.getByRole('dialog', { name: 'Proyectar' })
  await expect(screen.getByRole('img', { name: 'Escanea para entrar' })).toBeVisible()
  await expect(screen.getByText('3 participantes')).toBeVisible()
  await screen.getByRole('button', { name: 'Salir (Esc)' }).click()
  await page.getByRole('button', { name: 'Empezar concurso' }).click()
  await page.getByRole('button', { name: 'Proyectar' }).click()

  for (let round = 1; round <= 2; round++) {
    await expect(screen.getByText(`Pregunta ${round} de 2`)).toBeVisible({ timeout: 15_000 })
    // Todos responden la primera opción en cuanto se abre la pregunta.
    for (const p of phones) await p.locator('button.choice').first().click({ timeout: 15_000 })
    for (const p of phones)
      await expect(p.getByText(/Respuesta enviada|Correcto|Incorrecto/)).toBeVisible()
    // Respondieron todos: se cierra sola y se ve la respuesta con la clasificación.
    await expect(screen.getByRole('heading', { name: 'Clasificación' })).toBeVisible({
      timeout: 10_000,
    })
    await expect(screen.getByText('3 de 3 han respondido')).toBeVisible()
    for (const p of phones) {
      await expect(p.getByRole('heading', { name: 'Clasificación' })).toBeVisible({
        timeout: 10_000,
      })
      await expect(p.getByText(/vas \d\.º de 3/)).toBeVisible()
    }
    await screen.getByRole('button', { name: 'Pasar ya' }).click() // sin esperar los 8 s
  }

  // Podio con el ganador en el proyector y el puesto final en cada teléfono.
  await expect(screen.getByText(/^¡Gana .+!$/)).toBeVisible({ timeout: 10_000 })
  for (const p of phones) {
    await expect(p.getByText('¡Fin del concurso!')).toBeVisible({ timeout: 15_000 })
    await expect(p.getByText(/\d\.º de 3/)).toBeVisible()
  }
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: 'Clasificación final' })).toBeVisible()
  for (const p of phones) await p.context().close()
})
