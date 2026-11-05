import { describe, expect, it } from 'vitest'
import type { Unit } from './api'
import { isAnswering, scopeFor, splitRefs } from './chat'
import { answerAsText, docAsText } from './clipboard'
import { formatBytes, formatDuration } from './format'
import { unitTree } from './subjects'

const u = (id: string, kind: Unit['kind'], parent: string | null, position = 0): Unit => ({
  id,
  subject_id: 's',
  parent_id: parent,
  kind,
  title: id,
  position,
})

describe('unitTree', () => {
  it('ordena padres antes que hijos con su profundidad', () => {
    const tree = unitTree([
      u('t1', 'topic', 'm'),
      u('c', 'course', null),
      u('m', 'module', 'c'),
      u('t0', 'topic', null, 1),
    ])
    expect(tree.map((x) => `${x.unit.id}:${x.depth}`)).toEqual(['c:0', 'm:1', 't1:2', 't0:0'])
  })

  it('ignora unidades huérfanas y no entra en bucles', () => {
    const tree = unitTree([u('a', 'topic', 'b'), u('b', 'module', 'a')])
    expect(tree).toEqual([])
  })
})

describe('formato', () => {
  it('formatea tamaños y duraciones', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1,5 KB')
    expect(formatDuration(65_000)).toBe('1:05')
    expect(formatDuration(3_725_000)).toBe('1:02:05')
    expect(formatDuration(null)).toBe('—')
  })
})

describe('asistente', () => {
  it('separa el texto de las referencias y agrupa las seguidas', () => {
    expect(splitRefs('Uno ⟦1⟧. Dos ⟦2⟧⟦3⟧⟦2⟧ fin')).toEqual([
      { text: 'Uno ' },
      { refs: [1] },
      { text: '. Dos ' },
      { refs: [2, 3] },
      { text: ' fin' },
    ])
    expect(splitRefs('sin citas')).toEqual([{ text: 'sin citas' }])
    expect(splitRefs('')).toEqual([])
  })

  it('el ámbito sin asignatura es toda la biblioteca', () => {
    expect(scopeFor('', ['x'])).toEqual({
      subject_id: null,
      source_ids: [],
      unit_ids: [],
      exclude_source_ids: [],
    })
    expect(scopeFor('s1', ['a']).source_ids).toEqual(['a'])
    expect(isAnswering({ status: 'streaming' })).toBe(true)
    expect(isAnswering({ status: 'not_found' })).toBe(false)
  })
})

describe('copiar texto', () => {
  it('convierte un resumen en texto con referencias y fuentes', () => {
    const t = docAsText({
      title: 'Resumen',
      sections: [
        {
          title: 'Texto',
          prose: true,
          points: [
            { text: 'Uno.', refs: [1] },
            { text: 'Dos.', refs: [] },
          ],
        },
        { title: 'Ideas clave', prose: false, points: [{ text: 'A: b', refs: [2, 1] }] },
      ],
      citations: [
        { ref: 2, source_title: 'Clase 2' },
        { ref: 1, source_title: 'Clase 1' },
      ],
    } as never)
    expect(t).toBe(
      'Resumen\n\nTexto\nUno. [1] Dos.\n\nIdeas clave\n- A: b [2][1]\n\n[1] Clase 1\n[2] Clase 2',
    )
  })

  it('convierte una respuesta del asistente', () => {
    const t = answerAsText({
      content: 'VUCA es volátil ⟦1⟧⟦2⟧.',
      citations: [
        { ref: 1, source_title: 'Clase' },
        { ref: 2, source_title: 'Clase' },
      ],
    } as never)
    expect(t).toBe('VUCA es volátil [1][2].\n\n[1][2] Clase')
  })
})
