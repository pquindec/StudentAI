import { describe, expect, it } from 'vitest'
import type { Unit } from './api'
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
