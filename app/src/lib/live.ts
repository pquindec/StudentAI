import { es } from '../i18n/es'
import type { LiveParticipant, LiveResults } from './api'
import { grade10 } from './exams'

/** Estado de un participante, en texto para la tabla de la sala. */
export function participantState(p: LiveParticipant): string {
  if (p.status === 'pending') return es.live.pState.pending
  if (p.attempt_status === 'in_progress') return es.live.pState.answering(p.answered, p.total)
  if (p.attempt_status === 'grading') return es.live.pState.grading
  if (p.attempt_status === 'graded') return es.live.pState.graded
  return es.live.pState.waiting
}

/** Celda CSV segura: entre comillas y sin fórmulas (un nombre «=HYPERLINK(…)» no se ejecuta). */
export function csvCell(value: unknown): string {
  let text = value == null ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}

const num = (n: number | null | undefined) =>
  n == null ? '' : n.toLocaleString('es-ES', { maximumFractionDigits: 2 })

/** CSV de resultados (separador «;», como espera Excel en español). */
export function resultsCsv(results: LiveResults): string {
  const qs = [...results.questions].sort((a, b) => a.position - b.position)
  const header = [...es.live.csvHeader, ...qs.map((_, i) => es.live.csvQuestion(i + 1))]
  const rows = results.participants.map((p) => {
    const byQ = new Map(p.answers.map((a) => [a.question_id, a]))
    return [
      p.name,
      p.device ?? '',
      num(grade10(p.score, p.max_score)),
      num(p.score),
      num(p.max_score),
      ...qs.map((q) => num(byQ.get(q.question_id)?.points)),
    ]
  })
  return [header, ...rows].map((r) => r.map(csvCell).join(';')).join('\r\n') + '\r\n'
}

/** Media de la clase sobre 10 (solo de quienes ya tienen nota). */
export function classAverage(results: LiveResults): number | null {
  const grades = results.participants
    .map((p) => grade10(p.score, p.max_score))
    .filter((g): g is number => g != null)
  if (!grades.length) return null
  return Math.round((grades.reduce((a, b) => a + b, 0) / grades.length) * 10) / 10
}
