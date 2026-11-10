import { describe, expect, it } from 'vitest'
import type { LiveParticipant, LiveResults } from './api'
import { classAverage, csvCell, participantState, resultsCsv } from './live'

const person = (over: Partial<LiveParticipant> = {}): LiveParticipant => ({
  id: 'p1',
  name: 'Ana',
  device: 'Android · Chrome',
  status: 'admitted',
  online: true,
  answered: 0,
  total: 3,
  attempt_status: null,
  score: null,
  max_score: null,
  left_count: 0,
  joined_at: '2026-11-07T10:00:00.000Z',
  finished_at: null,
  ...over,
})

describe('participantState', () => {
  it('describe cada momento del participante', () => {
    expect(participantState(person({ status: 'pending' }))).toBe('Esperando admisión')
    expect(participantState(person())).toBe('Admitido · esperando')
    expect(participantState(person({ attempt_status: 'in_progress', answered: 2 }))).toBe(
      'Respondiendo · 2/3',
    )
    expect(participantState(person({ attempt_status: 'grading' }))).toBe('Entregado · corrigiendo')
    expect(participantState(person({ attempt_status: 'graded' }))).toBe('Entregado')
  })
})

describe('csv', () => {
  it('neutraliza fórmulas y escapa comillas', () => {
    expect(csvCell('=HYPERLINK("http://x")')).toBe(`"'=HYPERLINK(""http://x"")"`)
    expect(csvCell('+1')).toBe(`"'+1"`)
    expect(csvCell('@cmd')).toBe(`"'@cmd"`)
    expect(csvCell('Ana; Pérez')).toBe('"Ana; Pérez"')
    expect(csvCell(null)).toBe('""')
  })

  it('exporta una fila por participante con la nota y los puntos de cada pregunta', () => {
    const results: LiveResults = {
      questions: [
        {
          question_id: 'q2',
          position: 2,
          type: 'short',
          stem: 'B',
          options: [],
          answer: 'x',
          justification: null,
          rubric: [],
          evidence: [],
          answered: 1,
          ratio: 0.5,
        },
        {
          question_id: 'q1',
          position: 1,
          type: 'single',
          stem: 'A',
          options: ['a', 'b'],
          answer: 0,
          justification: null,
          rubric: [],
          evidence: [],
          answered: 1,
          ratio: 1,
        },
      ],
      participants: [
        {
          ...person({ name: '=Eva', attempt_status: 'graded', score: 1.5, max_score: 2 }),
          answers: [
            {
              question_id: 'q1',
              answer: 0,
              points: 1,
              is_correct: true,
              feedback: null,
              graded_by: 'auto',
              adjusted: false,
            },
            {
              question_id: 'q2',
              answer: 'x',
              points: 0.5,
              is_correct: false,
              feedback: 'Bien',
              graded_by: 'ai',
              adjusted: true,
            },
          ],
        },
      ],
    }
    const lines = resultsCsv(results).trim().split('\r\n')
    expect(lines[0]).toBe('"Nombre";"Dispositivo";"Nota (/10)";"Puntos";"Máximo";"P1";"P2"')
    expect(lines[1]).toBe(`"'=Eva";"Android · Chrome";"7,5";"1,5";"2";"1";"0,5"`)
    expect(classAverage(results)).toBe(7.5)
    expect(classAverage({ questions: [], participants: [] })).toBeNull()
  })
})
