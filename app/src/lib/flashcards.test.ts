import { describe, expect, it } from 'vitest'
import { formatInterval, formatStudy, isDeckGenerating, percent, ratingFromKey } from './flashcards'

describe('flashcards', () => {
  it('formatea el intervalo de cada botón', () => {
    expect(formatInterval(30)).toBe('<1 min')
    expect(formatInterval(600)).toBe('10 min')
    expect(formatInterval(3 * 3600)).toBe('3 h')
    expect(formatInterval(2.4 * 86400)).toBe('2 d')
    expect(formatInterval(31 * 86400)).toBe('1 mes')
    expect(formatInterval(95 * 86400)).toBe('3 meses')
    expect(formatInterval(548 * 86400)).toBe('1,5 años')
  })
  it('formatea el tiempo de estudio', () => {
    expect(formatStudy(0)).toBe('0 min')
    expect(formatStudy(45 * 60_000)).toBe('45 min')
    expect(formatStudy(80 * 60_000)).toBe('1 h 20 min')
    expect(formatStudy(120 * 60_000)).toBe('2 h')
  })
  it('porcentajes, estados y atajos', () => {
    expect(percent(1, 3)).toBe(33)
    expect(percent(1, 0)).toBeNull()
    expect(isDeckGenerating({ status: 'running' })).toBe(true)
    expect(isDeckGenerating({ status: 'ready' })).toBe(false)
    expect(ratingFromKey('3')).toBe(3)
    expect(ratingFromKey('5')).toBeNull()
  })
})
