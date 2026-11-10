import { describe, expect, it } from 'vitest'
import type { ManualExam } from './api'
import { emptyDraft, emptyQuestion, fromManual, move, removeOption, toPayload } from './manualExam'

const filled = () => {
  const d = emptyDraft()
  d.title = '  Parcial  '
  d.questions = [
    { ...emptyQuestion('single'), stem: '¿2+2?', options: ['3', ' 4 ', '5'], correct: 1 },
    { ...emptyQuestion('true_false'), stem: 'El agua hierve a 100 °C', truth: true },
    {
      ...emptyQuestion('short'),
      stem: 'Define OSI',
      model: 'Modelo de 7 capas',
      rubric: 'Siete capas\n\n  Referencia  \n',
      justification: ' Es el estándar ',
      sourceId: 'src-1',
    },
  ]
  return d
}

describe('toPayload', () => {
  it('limpia el borrador y lo convierte al cuerpo de la API', () => {
    const out = toPayload(filled())
    expect(out.errors).toEqual([])
    if (!('body' in out)) throw new Error('sin cuerpo')
    expect(out.body.title).toBe('Parcial')
    expect(out.body.time_limit_min).toBeNull()
    const [single, tf, short] = out.body.questions
    expect(single).toMatchObject({ options: ['3', '4', '5'], answer: 1, rubric: [] })
    expect(tf).toMatchObject({ type: 'true_false', answer: true, options: [] })
    expect(short).toMatchObject({
      answer: 'Modelo de 7 capas',
      rubric: ['Siete capas', 'Referencia'],
      justification: 'Es el estándar',
      source_id: 'src-1',
    })
    expect(single.source_id).toBeNull()
  })

  it('explica en español qué falta, pregunta por pregunta', () => {
    const d = emptyDraft()
    d.mode = 'timed'
    d.minutes = 0
    d.questions = [
      { ...emptyQuestion('single'), options: ['a', 'A', ''] },
      emptyQuestion('true_false'),
      { ...emptyQuestion('short'), stem: 'x' },
    ]
    const out = toPayload(d)
    expect(out.errors).toEqual([
      'Ponle un título al examen.',
      'El tiempo límite debe estar entre 1 y 240 minutos.',
      'Pregunta 1: escribe el enunciado.',
      'Pregunta 1: hay una opción vacía; rellénala o quítala.',
      'Pregunta 1: hay opciones repetidas.',
      'Pregunta 1: marca cuál es la opción correcta.',
      'Pregunta 2: escribe el enunciado.',
      'Pregunta 2: indica si es verdadera o falsa.',
      'Pregunta 3: escribe la respuesta modelo.',
    ])
    expect(toPayload({ ...filled(), questions: [] }).errors).toEqual([
      'Añade al menos una pregunta.',
    ])
  })
})

describe('edición', () => {
  it('quitar una opción mantiene marcada la correcta', () => {
    const q = { ...emptyQuestion(), options: ['a', 'b', 'c', 'd'], correct: 2 }
    expect(removeOption(q, 0)).toMatchObject({ options: ['b', 'c', 'd'], correct: 1 })
    expect(removeOption(q, 3).correct).toBe(2)
    expect(removeOption(q, 2).correct).toBeNull()
  })

  it('mover preguntas', () => {
    expect(move(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a'])
    expect(move(['a', 'b'], 0, -1)).toEqual(['a', 'b'])
  })

  it('carga un examen guardado y vuelve a dar el mismo cuerpo', () => {
    const out = toPayload(filled())
    if (!('body' in out)) throw new Error('sin cuerpo')
    const saved: ManualExam = { ...out.body, editable: true }
    const again = toPayload(fromManual(saved))
    expect('body' in again && again.body).toEqual(out.body)
  })
})
