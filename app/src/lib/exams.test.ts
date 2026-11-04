import { describe, expect, it } from 'vitest'
import { es } from '../i18n/es'
import type { AnswerState, AttemptQuestion } from './api'
import { answerText, formatRemaining, grade10, isAnswered, isGenerating, outcome } from './exams'

const base: AnswerState = {
  question_id: 'q',
  flagged: false,
  checked: false,
  rubric: [],
  evidence: [],
}
const single: AttemptQuestion = {
  id: 'q',
  type: 'single',
  stem: '¿?',
  options: ['uno', 'dos', 'tres'],
  difficulty: 'easy',
}

describe('exams', () => {
  it('detecta la generación en curso', () => {
    expect(isGenerating({ status: 'queued' })).toBe(true)
    expect(isGenerating({ status: 'running' })).toBe(true)
    expect(isGenerating({ status: 'insufficient' })).toBe(false)
  })

  it('calcula la nota sobre 10 sin negativos', () => {
    expect(grade10(15, 20)).toBe(7.5)
    expect(grade10(-2, 20)).toBe(0)
    expect(grade10(2, 3)).toBe(6.7)
    expect(grade10(null, 20)).toBeNull()
    expect(grade10(3, 0)).toBeNull()
  })

  it('formatea el tiempo restante', () => {
    expect(formatRemaining(65_000)).toBe('1:05')
    expect(formatRemaining(3_725_000)).toBe('1:02:05')
    expect(formatRemaining(-5)).toBe('0:00')
    expect(formatRemaining(400)).toBe('0:01')
  })

  it('distingue respuestas vacías (0 y false sí cuentan)', () => {
    expect(isAnswered(undefined)).toBe(false)
    expect(isAnswered({ answer: null })).toBe(false)
    expect(isAnswered({ answer: '   ' })).toBe(false)
    expect(isAnswered({ answer: 0 })).toBe(true)
    expect(isAnswered({ answer: false })).toBe(true)
    expect(isAnswered({ answer: 'algo' })).toBe(true)
  })

  it('muestra la respuesta legible', () => {
    expect(answerText(single, 1)).toBe('B) dos')
    expect(answerText({ ...single, type: 'true_false', options: [] }, false)).toBe(
      es.exams.falseLabel,
    )
    expect(answerText(single, null)).toBe(es.exams.blank)
    expect(answerText({ ...single, type: 'short', options: [] }, 'texto')).toBe('texto')
  })

  it('clasifica el resultado', () => {
    expect(outcome({ ...base, answer: null })).toBe('blank')
    expect(outcome({ ...base, answer: 1, is_correct: true, points: 1 })).toBe('correct')
    expect(outcome({ ...base, answer: 2, is_correct: false, points: -0.25 })).toBe('incorrect')
    expect(outcome({ ...base, answer: 'x', is_correct: false, points: 0.5 })).toBe('partial')
  })
})
