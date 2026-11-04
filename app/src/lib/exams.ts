import { es } from '../i18n/es'
import type { AnswerState, AttemptQuestion, Exam } from './api'

export const isGenerating = (e: Pick<Exam, 'status'>) =>
  e.status === 'queued' || e.status === 'running'

/** Nota sobre 10 con un decimal (la penalización puede dar negativos: se limita a 0). */
export function grade10(score: number | null | undefined, max: number | null | undefined) {
  if (score == null || !max) return null
  return Math.round((Math.max(0, score) / max) * 100) / 10
}

/** Tiempo restante en m:ss (o h:mm:ss). */
export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const ss = String(s).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

export function isAnswered(a: Pick<AnswerState, 'answer'> | undefined): boolean {
  if (!a || a.answer === null || a.answer === undefined) return false
  return typeof a.answer !== 'string' || a.answer.trim() !== ''
}

/** Texto legible de una respuesta (índice → opción, booleano → Verdadero/Falso). */
export function answerText(q: AttemptQuestion, answer: unknown): string {
  if (answer === null || answer === undefined || answer === '') return es.exams.blank
  if (q.type === 'single' && typeof answer === 'number') {
    return `${'ABCDE'[answer]}) ${q.options[answer] ?? ''}`
  }
  if (typeof answer === 'boolean') return answer ? es.exams.trueLabel : es.exams.falseLabel
  return String(answer)
}

export type Outcome = 'correct' | 'incorrect' | 'partial' | 'blank'

export function outcome(a: AnswerState): Outcome {
  if (!isAnswered(a)) return 'blank'
  if (a.points != null && a.points > 0 && a.points < 1) return 'partial'
  return a.is_correct ? 'correct' : 'incorrect'
}
