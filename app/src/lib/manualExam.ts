import { es } from '../i18n/es'
import type { ManualExam, ManualExamIn, ManualQuestion } from './api'

export type QType = ManualQuestion['type']
export type Difficulty = ManualQuestion['difficulty']
export const MAX_QUESTIONS = 50
export const MIN_OPTIONS = 2
export const MAX_OPTIONS = 6
export const PENALTIES = [0, 0.25, 0.33, 0.5] as const

/** Pregunta tal como se edita: guarda lo de todos los tipos para no perderlo al cambiar de tipo. */
export interface DraftQuestion {
  key: string
  type: QType
  stem: string
  options: string[]
  correct: number | null // opción múltiple
  truth: boolean | null // verdadero / falso
  model: string // respuesta corta: respuesta modelo
  rubric: string // respuesta corta: un punto por línea
  justification: string
  difficulty: Difficulty
  sourceId: string
}

export interface Draft {
  title: string
  mode: 'practice' | 'timed'
  minutes: number
  penalty: number
  questions: DraftQuestion[]
}

let seq = 0
const key = () => `q${Date.now().toString(36)}${(seq++).toString(36)}`

export function emptyQuestion(type: QType = 'single'): DraftQuestion {
  return {
    key: key(),
    type,
    stem: '',
    options: ['', '', '', ''],
    correct: null,
    truth: null,
    model: '',
    rubric: '',
    justification: '',
    difficulty: 'medium',
    sourceId: '',
  }
}

export function emptyDraft(): Draft {
  return { title: '', mode: 'practice', minutes: 30, penalty: 0, questions: [emptyQuestion()] }
}

export function fromManual(m: ManualExam): Draft {
  return {
    title: m.title,
    mode: m.mode ?? 'practice',
    minutes: m.time_limit_min ?? 30,
    penalty: m.penalty ?? 0,
    questions: m.questions.map((q) => ({
      ...emptyQuestion(q.type),
      stem: q.stem,
      options: q.type === 'single' ? [...(q.options ?? [])] : ['', '', '', ''],
      correct: q.type === 'single' && typeof q.answer === 'number' ? q.answer : null,
      truth: q.type === 'true_false' && typeof q.answer === 'boolean' ? q.answer : null,
      model: q.type === 'short' && typeof q.answer === 'string' ? q.answer : '',
      rubric: (q.rubric ?? []).join('\n'),
      justification: q.justification ?? '',
      difficulty: q.difficulty ?? 'medium',
      sourceId: q.source_id ?? '',
    })),
  }
}

/** Quita una opción y mantiene marcada la correcta (o la desmarca si era esa). */
export function removeOption(q: DraftQuestion, i: number): DraftQuestion {
  const options = q.options.filter((_, j) => j !== i)
  const correct =
    q.correct == null || q.correct === i ? null : q.correct > i ? q.correct - 1 : q.correct
  return { ...q, options, correct }
}

export function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list
  const out = [...list]
  const [item] = out.splice(from, 1)
  out.splice(to, 0, item)
  return out
}

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

/** Valida el borrador (mismas reglas que el backend) y lo convierte al cuerpo de la API. */
export function toPayload(d: Draft): { body: ManualExamIn; errors: [] } | { errors: string[] } {
  const E = es.examEditor.errors
  const errors: string[] = []
  if (!d.title.trim()) errors.push(E.title)
  if (d.questions.length === 0) errors.push(E.none)
  if (d.questions.length > MAX_QUESTIONS) errors.push(E.tooMany(MAX_QUESTIONS))
  if (d.mode === 'timed' && !(d.minutes >= 1 && d.minutes <= 240)) errors.push(E.minutes)
  const questions: ManualQuestion[] = []
  d.questions.forEach((q, i) => {
    const n = i + 1
    const stem = q.stem.trim()
    if (!stem) errors.push(E.stem(n))
    const base = {
      type: q.type,
      stem,
      justification: q.justification.trim(),
      difficulty: q.difficulty,
      source_id: q.sourceId || null,
      options: [] as string[],
      rubric: [] as string[],
    }
    if (q.type === 'single') {
      const options = q.options.map((o) => o.trim())
      const filled = options.filter(Boolean)
      if (filled.length < MIN_OPTIONS) errors.push(E.options(n, MIN_OPTIONS))
      else if (filled.length !== options.length) errors.push(E.emptyOption(n))
      if (new Set(filled.map((o) => o.toLocaleLowerCase('es'))).size !== filled.length)
        errors.push(E.repeated(n))
      if (q.correct == null || q.correct >= options.length) errors.push(E.correct(n))
      questions.push({ ...base, options, answer: q.correct ?? 0 })
    } else if (q.type === 'true_false') {
      if (q.truth == null) errors.push(E.truth(n))
      questions.push({ ...base, answer: q.truth ?? false })
    } else {
      const model = q.model.trim()
      if (!model) errors.push(E.model(n))
      questions.push({ ...base, answer: model, rubric: lines(q.rubric) })
    }
  })
  if (errors.length) return { errors }
  return {
    errors: [],
    body: {
      title: d.title.trim(),
      mode: d.mode,
      time_limit_min: d.mode === 'timed' ? d.minutes : null,
      penalty: d.penalty,
      questions,
    },
  }
}
