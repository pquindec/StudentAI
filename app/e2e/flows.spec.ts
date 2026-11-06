import { type Page } from '@playwright/test'
import { expect, seed, test, TEXT } from './fixtures.ts'

const go = (page: Page, section: string) =>
  page.getByRole('navigation').getByRole('button', { name: section, exact: true }).click()

test('crear una asignatura y pegar texto', async ({ page, backend }) => {
  await page.goto('/')
  await go(page, 'Mis asignaturas')
  await page.getByRole('button', { name: 'Nueva asignatura' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nueva asignatura' })
  await expect(dialog.getByRole('button', { name: 'Crear' })).toBeDisabled()
  await dialog.getByRole('textbox', { name: 'Nombre' }).fill('Redes')
  await dialog.getByRole('button', { name: 'Crear' }).click()
  await expect(page.getByRole('heading', { name: 'Redes', level: 1 })).toBeVisible()

  await go(page, 'Importar archivos')
  await page.getByRole('button', { name: /Pega texto o escribe una nota/ }).click()
  const paste = page.getByRole('main')
  await paste.getByRole('radio', { name: 'Texto pegado' }).check()
  await paste.getByRole('textbox', { name: 'Título', exact: true }).fill('Modelo OSI')
  await paste.getByRole('textbox', { name: /Contenido/ }).fill(TEXT)
  await paste.getByRole('button', { name: 'Guardar en la biblioteca' }).click()

  await go(page, 'Biblioteca')
  const row = page.getByRole('row', { name: /Modelo OSI/ })
  await expect(row).toContainText('Listo')
  const sources = await backend.api<{ total: number }>('GET', '/sources')
  expect(sources.total).toBe(1)
})

test('generar un resumen con citas', async ({ page, backend }) => {
  await seed(backend)
  await page.goto('/')
  await go(page, 'Resúmenes')
  await page.getByRole('button', { name: 'Generar resumen' }).click()
  const dialog = page.getByRole('dialog', { name: 'Generar resumen' })
  await dialog.getByRole('checkbox', { name: /Tema 1/ }).check()
  await dialog.getByRole('button', { name: 'Generar' }).click()
  await expect(dialog).toBeHidden()
  // Al generarlo se abre el resumen: cada idea con sus citas comprobadas.
  const main = page.getByRole('main')
  await expect(main.getByRole('heading', { name: 'Resumen · Tema 1' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(main.getByText(/citas, todas comprobadas contra tus fuentes/)).toBeVisible()
  await main.getByRole('button', { name: 'Cita 1' }).first().click()
  await expect(page.getByText(/Párrafo \d+: la arquitectura/).first()).toBeVisible()
})

test('preguntar al asistente y ver la cita', async ({ page, backend }) => {
  await seed(backend)
  await page.goto('/')
  await go(page, 'Asistente IA')
  const box = page.getByRole('textbox', { name: /Escribe tu pregunta/ })
  await box.fill('¿Qué define la arquitectura?')
  await box.press('Enter')
  const main = page.getByRole('main')
  await expect(
    main.getByRole('paragraph').filter({ hasText: '¿Qué define la arquitectura?' }),
  ).toBeVisible()
  // La respuesta lleva su cita y avisa de la cita inventada que se descartó.
  await expect(main.getByRole('button', { name: 'Cita 1' })).toBeVisible()
  await expect(main.getByText(/1 cita no existía y se descartó/)).toBeVisible()
})

test('crear un mazo y repasar una tarjeta', async ({ page, backend }) => {
  await seed(backend)
  await page.goto('/')
  await go(page, 'Flashcards')
  await page.getByRole('button', { name: 'Nuevo mazo' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuevo mazo' })
  await dialog.getByRole('spinbutton', { name: 'Número de tarjetas' }).fill('5')
  await dialog.getByRole('button', { name: 'Crear tarjetas' }).click()
  await expect(dialog).toBeHidden()

  const review = page.getByRole('button', { name: 'Repasar' })
  await expect(review).toBeEnabled({ timeout: 30_000 })
  await review.click()
  await page.getByRole('button', { name: /Mostrar respuesta/ }).click()
  await page.getByRole('button', { name: /^Bien/ }).click()
  // La valorada vuelve en 10 min (aprendizaje); ahora sale la siguiente nueva.
  await expect(page.getByText('Aprendiendo 0 · Repasos 0 · Nuevas 4')).toBeVisible()
})

test('crear un examen, contestar y comprobar', async ({ page, backend }) => {
  await seed(backend)
  await page.goto('/')
  await go(page, 'Exámenes')
  await page.getByRole('button', { name: 'Nuevo examen' }).click()
  const dialog = page.getByRole('dialog', { name: 'Nuevo examen' })
  await dialog.getByRole('spinbutton', { name: 'Número de preguntas' }).fill('1')
  await dialog.getByRole('checkbox', { name: 'Verdadero / falso' }).uncheck()
  await dialog.getByRole('button', { name: 'Generar examen' }).click()
  await expect(dialog).toBeHidden()

  // Al generarlo se abre el examen; «Empezar» aparece cuando está listo.
  await page.getByRole('button', { name: 'Empezar' }).click({ timeout: 30_000 })
  await page.getByRole('radio').first().check()
  await page.getByRole('button', { name: /Comprobar/ }).click()
  await expect(page.getByText(/Correcta|Incorrecta/).first()).toBeVisible()
  await expect(page.getByText('Evidencia en tus fuentes')).toBeVisible()
  await expect(page.getByRole('blockquote')).toContainText('la arquitectura número') // literal
  await page.getByRole('button', { name: 'Entregar' }).click()
  const confirm = page.getByRole('dialog')
  if (await confirm.isVisible().catch(() => false))
    await confirm.getByRole('button', { name: /Entregar/ }).click()
  await expect(page.getByRole('main')).toContainText(/Nota\s*\d+([.,]\d+)?\/10/)
  await expect(page.getByRole('heading', { name: 'Dónde fallaste más' })).toBeVisible()
})
