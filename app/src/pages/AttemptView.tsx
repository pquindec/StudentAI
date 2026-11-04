import { useCallback, useEffect, useRef, useState } from 'react'
import { CitationPanel } from '../components/Citations'
import {
  Button,
  Card,
  ConfirmButton,
  ErrorText,
  inputClass,
  Loading,
  Modal,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, ApiError, type AnswerState, type Attempt, type AttemptQuestion } from '../lib/api'
import { answerText, formatRemaining, grade10, isAnswered, outcome } from '../lib/exams'
import { useNavigate } from '../lib/nav'
import { errorMessage } from '../lib/useQuery'

const LETTERS = 'ABCDE'

export function AttemptView({ id }: { id: string }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      setAttempt(await api.getAttempt(id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [id])
  useEffect(() => {
    void load()
  }, [load])
  const grading = attempt?.status === 'grading'
  useEffect(() => {
    if (!grading) return
    const t = window.setInterval(() => void load(), 1500)
    return () => window.clearInterval(t)
  }, [grading, load])

  if (!attempt) {
    return (
      <div className="mx-auto max-w-3xl px-10 py-10">
        {error ? <ErrorText>{error}</ErrorText> : <Loading />}
      </div>
    )
  }
  if (attempt.status === 'in_progress') {
    return <Taking key={attempt.id} attempt={attempt} onClosed={setAttempt} />
  }
  return <Results attempt={attempt} />
}

function Back({ examId }: { examId: string }) {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      className="mb-3 text-sm text-zinc-500 hover:underline"
      onClick={() => navigate({ name: 'exam', id: examId })}
    >
      ← {es.exams.backToExam}
    </button>
  )
}

// ---------------------------------------------------------------- responder

function Taking({ attempt, onClosed }: { attempt: Attempt; onClosed: (a: Attempt) => void }) {
  const qs = attempt.questions
  const [index, setIndex] = useState(Math.min(attempt.current_index, qs.length - 1))
  const [answers, setAnswers] = useState<Record<string, AnswerState>>(() =>
    Object.fromEntries(attempt.answers.map((a) => [a.question_id, a])),
  )
  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      attempt.answers
        .filter((a) => typeof a.answer === 'string')
        .map((a) => [a.question_id, a.answer as string]),
    ),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const timer = useRef<number | null>(null)
  const practice = attempt.mode === 'practice'
  const q = qs[index]!
  const state = answers[q.id]

  const finish = useCallback(async () => {
    setSubmitting(true)
    try {
      onClosed(await api.submitAttempt(attempt.id))
    } catch {
      // Ya cerrado (p. ej. por tiempo): basta con recargarlo.
      onClosed(await api.getAttempt(attempt.id))
    }
  }, [attempt.id, onClosed])

  const save = useCallback(
    async (qid: string, body: Parameters<typeof api.saveAnswer>[2]) => {
      setSaving(true)
      setError(null)
      try {
        const s = await api.saveAnswer(attempt.id, qid, body)
        setAnswers((prev) => ({ ...prev, [qid]: s }))
      } catch (err) {
        setError(errorMessage(err))
        if (
          err instanceof ApiError &&
          (err.code === 'time_over' || err.code === 'attempt_closed')
        ) {
          void finish()
        }
      } finally {
        setSaving(false)
      }
    },
    [attempt.id, finish],
  )

  // Las respuestas cortas se guardan al dejar de escribir.
  const flushDraft = useCallback(() => {
    if (timer.current == null) return
    window.clearTimeout(timer.current)
    timer.current = null
    const text = drafts[q.id] ?? ''
    void save(q.id, { answer: text.trim() ? text : null, set_answer: true })
  }, [drafts, q.id, save])
  useEffect(
    () => () => {
      if (timer.current != null) window.clearTimeout(timer.current)
    },
    [],
  )

  const choose = (value: number | boolean) => {
    setAnswers((prev) => ({
      ...prev,
      [q.id]: { ...(prev[q.id] ?? emptyState(q.id)), answer: value },
    }))
    void save(q.id, { answer: value, set_answer: true })
  }
  const type = (text: string) => {
    setDrafts((prev) => ({ ...prev, [q.id]: text }))
    setAnswers((prev) => ({
      ...prev,
      [q.id]: { ...(prev[q.id] ?? emptyState(q.id)), answer: text },
    }))
    if (timer.current != null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = null
      void save(q.id, { answer: text.trim() ? text : null, set_answer: true })
    }, 700)
  }
  const go = (i: number) => {
    flushDraft()
    setIndex(i)
    void save(qs[i]!.id, { set_answer: false, index: i })
  }
  const toggleFlag = () =>
    void save(q.id, { set_answer: false, flagged: !(state?.flagged ?? false) })
  const check = async () => {
    flushDraft()
    setError(null)
    try {
      const s = await api.checkAnswer(attempt.id, q.id)
      setAnswers((prev) => ({ ...prev, [q.id]: s }))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  // Temporizador (modo con tiempo): la hora límite la impone el backend.
  const deadline = attempt.deadline_at ? Date.parse(attempt.deadline_at) : null
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (deadline == null) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [deadline])
  const remaining = deadline != null ? deadline - now : null
  const expired = remaining != null && remaining <= 0
  useEffect(() => {
    if (expired) void finish()
  }, [expired, finish])

  const unanswered = qs.filter((x) => !isAnswered(answers[x.id])).length
  const locked = state?.checked ?? false

  return (
    <div className="mx-auto max-w-3xl px-10 py-10">
      <Back examId={attempt.exam_id} />
      <div className="mb-4 flex items-center gap-3">
        <h1 className="flex-1 truncate text-xl font-semibold">{attempt.exam_title}</h1>
        {remaining != null && (
          <span
            className={`rounded-md px-2 py-1 text-sm font-medium tabular-nums ${
              remaining < 60_000
                ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200'
                : 'bg-zinc-100 dark:bg-zinc-800'
            }`}
            role="timer"
          >
            {es.exams.timeLeft(formatRemaining(remaining))}
          </span>
        )}
        <span className="w-20 text-right text-xs text-zinc-500">
          {saving ? es.exams.saving : es.exams.saved}
        </span>
      </div>

      <nav className="mb-6 flex flex-wrap gap-1" aria-label={es.exams.title}>
        {qs.map((x, i) => {
          const a = answers[x.id]
          return (
            <button
              key={x.id}
              type="button"
              onClick={() => go(i)}
              aria-current={i === index ? 'step' : undefined}
              aria-label={es.exams.question(i + 1, qs.length)}
              className={`relative h-8 w-8 rounded text-xs font-medium tabular-nums ${
                i === index
                  ? 'bg-accent-600 text-white'
                  : isAnswered(a)
                    ? 'bg-accent-100 text-accent-700 dark:bg-accent-700/30 dark:text-accent-100'
                    : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
              }`}
            >
              {i + 1}
              {a?.flagged && (
                <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-amber-500" />
              )}
            </button>
          )
        })}
      </nav>

      <Card className="space-y-4">
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span className="flex-1">
            {es.exams.question(index + 1, qs.length)} · {es.exams.type[q.type as QType]}
          </span>
          <button
            type="button"
            onClick={toggleFlag}
            aria-pressed={state?.flagged ?? false}
            className={`rounded px-2 py-0.5 ${
              state?.flagged
                ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
                : 'hover:bg-zinc-100 dark:hover:bg-zinc-800'
            }`}
          >
            ⚑ {state?.flagged ? es.exams.flagged : es.exams.flag}
          </button>
        </div>
        <p className="text-base font-medium whitespace-pre-wrap">{q.stem}</p>
        <AnswerInput
          q={q}
          value={q.type === 'short' ? (drafts[q.id] ?? '') : state?.answer}
          disabled={locked}
          onChoose={choose}
          onType={type}
        />
        {practice && locked && state && <Feedback q={q} a={state} />}
      </Card>

      <ErrorText>{error}</ErrorText>
      <div className="mt-4 flex items-center gap-2">
        <Button disabled={index === 0} onClick={() => go(index - 1)}>
          {es.exams.prev}
        </Button>
        <Button disabled={index === qs.length - 1} onClick={() => go(index + 1)}>
          {es.exams.next}
        </Button>
        <div className="flex-1" />
        {practice && !locked && (
          <Button disabled={!isAnswered(state)} onClick={() => void check()}>
            {es.exams.check}
          </Button>
        )}
        <Button variant="primary" disabled={submitting} onClick={() => setConfirm(true)}>
          {es.exams.submit}
        </Button>
      </div>

      <Modal open={confirm} title={es.exams.submit} onClose={() => setConfirm(false)}>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {es.exams.submitConfirm(unanswered)}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => setConfirm(false)}>{es.common.cancel}</Button>
          <Button
            variant="primary"
            disabled={submitting}
            onClick={() => {
              flushDraft()
              setConfirm(false)
              void finish()
            }}
          >
            {es.exams.submit}
          </Button>
        </div>
      </Modal>
    </div>
  )
}

type QType = keyof typeof es.exams.type

const emptyState = (qid: string): AnswerState => ({
  question_id: qid,
  flagged: false,
  checked: false,
  rubric: [],
  evidence: [],
})

function AnswerInput({
  q,
  value,
  disabled,
  onChoose,
  onType,
}: {
  q: AttemptQuestion
  value: unknown
  disabled: boolean
  onChoose: (v: number | boolean) => void
  onType: (t: string) => void
}) {
  if (q.type === 'short') {
    return (
      <textarea
        className={`${inputClass} min-h-28`}
        placeholder={es.exams.shortPlaceholder}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        onChange={(e) => onType(e.target.value)}
      />
    )
  }
  const choices: { label: string; v: number | boolean }[] =
    q.type === 'true_false'
      ? [
          { label: es.exams.trueLabel, v: true },
          { label: es.exams.falseLabel, v: false },
        ]
      : q.options.map((o, i) => ({ label: `${LETTERS[i]}) ${o}`, v: i }))
  return (
    <div className="space-y-2" role="radiogroup">
      {choices.map((c) => {
        const on = value === c.v
        return (
          <button
            key={String(c.v)}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onChoose(c.v)}
            className={`block w-full rounded-lg border px-3 py-2 text-left text-sm ${
              on
                ? 'border-accent-600 bg-accent-50 dark:bg-accent-700/20'
                : 'border-zinc-200 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800'
            } disabled:cursor-default`}
          >
            {c.label}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------- corrección

const OUTCOME_STYLE = {
  correct: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  partial: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  incorrect: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  blank: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
} as const

/** Resultado de una pregunta: tu respuesta, la correcta, por qué y la evidencia literal. */
function Feedback({ q, a }: { q: AttemptQuestion; a: AnswerState }) {
  const o = outcome(a)
  return (
    <div className="space-y-3 border-t border-zinc-100 pt-3 text-sm dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${OUTCOME_STYLE[o]}`}>
          {es.exams[o]}
        </span>
        {a.graded_by === 'ai' && (
          <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs text-violet-800 dark:bg-violet-900/40 dark:text-violet-200">
            {es.exams.aiGraded}
          </span>
        )}
        {a.points != null && (
          <span className="text-xs text-zinc-500 tabular-nums">
            {a.points.toLocaleString('es-ES', { maximumFractionDigits: 2 })}
          </span>
        )}
      </div>
      <p>
        <span className="text-zinc-500">{es.exams.yourAnswer}: </span>
        {answerText(q, a.answer)}
      </p>
      {a.correct_answer !== undefined && a.correct_answer !== null && (
        <p>
          <span className="text-zinc-500">
            {q.type === 'short' ? es.exams.modelAnswer : es.exams.correctAnswer}:{' '}
          </span>
          {answerText(q, a.correct_answer)}
        </p>
      )}
      {a.feedback && <p className="text-zinc-600 dark:text-zinc-400">{a.feedback}</p>}
      {a.rubric.length > 0 && (
        <div>
          <span className="text-zinc-500">{es.exams.rubric}:</span>
          <ul className="ml-5 list-disc">
            {a.rubric.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {a.justification && (
        <p>
          <span className="text-zinc-500">{es.exams.why}: </span>
          {a.justification}
        </p>
      )}
      {a.evidence.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs text-zinc-500">{es.exams.evidence}</div>
          {a.evidence.map((c) => (
            <CitationPanel key={c.ref} ref_={c.ref} cite={c} />
          ))}
        </div>
      )}
    </div>
  )
}

function Results({ attempt }: { attempt: Attempt }) {
  const navigate = useNavigate()
  const byId = new Map(attempt.answers.map((a) => [a.question_id, a]))
  const g = grade10(attempt.score, attempt.max_score)
  const failed = attempt.questions.filter((q) => {
    const a = byId.get(q.id)
    return a && outcome(a) !== 'correct'
  })

  return (
    <div className="mx-auto max-w-3xl px-10 py-10">
      <Back examId={attempt.exam_id} />
      <div className="mb-6 flex items-center gap-3">
        <h1 className="flex-1 truncate text-xl font-semibold">{attempt.exam_title}</h1>
        <ConfirmButton
          label={es.exams.deleteAttempt}
          title={es.exams.deleteAttempt}
          onConfirm={async () => {
            await api.deleteAttempt(attempt.id)
            navigate({ name: 'exam', id: attempt.exam_id })
          }}
        />
      </div>

      {attempt.status === 'grading' ? (
        <Card className="flex items-center gap-3">
          <Loading />
          <span className="text-sm text-zinc-500">
            {attempt.progress_message ?? es.exams.grading}
          </span>
        </Card>
      ) : (
        <div className="space-y-6">
          <Card className="flex items-baseline gap-4">
            <span className="text-sm text-zinc-500">{es.exams.score}</span>
            <span className="text-3xl font-semibold tabular-nums">
              {g != null ? `${g.toLocaleString('es-ES')}/10` : '—'}
            </span>
            {attempt.score != null && attempt.max_score != null && (
              <span className="text-sm text-zinc-500">
                {es.exams.scoreOf(attempt.score, attempt.max_score)} ·{' '}
                {es.exams.penaltyNote(attempt.penalty)}
              </span>
            )}
          </Card>

          {attempt.weak_topics.length > 0 && (
            <Card>
              <h2 className="font-medium">{es.exams.weak}</h2>
              <p className="mb-3 text-xs text-zinc-500">{es.exams.weakHint}</p>
              <ul className="space-y-2">
                {attempt.weak_topics.map((w) => (
                  <li key={w.source_id ?? w.source_title} className="text-sm">
                    <div className="flex items-center gap-3">
                      <span className="flex-1 truncate">
                        {w.source_title}
                        {w.units.length > 0 && (
                          <span className="text-zinc-500"> · {w.units.join(', ')}</span>
                        )}
                      </span>
                      <span className="text-xs text-zinc-500 tabular-nums">
                        {es.exams.weakRow(w.correct, w.questions)}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
                      <div
                        className="h-full bg-accent-600"
                        style={{ width: `${Math.round(w.ratio * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <div className="space-y-4">
            {attempt.questions.map((q, i) => {
              const a = byId.get(q.id)
              return (
                <Card key={q.id} className="space-y-3">
                  <div className="text-xs text-zinc-500">
                    {es.exams.question(i + 1, attempt.questions.length)} ·{' '}
                    {es.exams.type[q.type as QType]}
                  </div>
                  <p className="font-medium whitespace-pre-wrap">{q.stem}</p>
                  {q.type === 'single' && (
                    <ol className="space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                      {q.options.map((o, j) => (
                        <li key={o}>
                          {LETTERS[j]}) {o}
                        </li>
                      ))}
                    </ol>
                  )}
                  {a && <Feedback q={q} a={a} />}
                </Card>
              )
            })}
          </div>

          <Card>
            <h2 className="font-medium">{es.exams.review}</h2>
            {failed.length === 0 ? (
              <p className="mt-2 text-sm text-zinc-500">{es.exams.nothingToReview}</p>
            ) : (
              <>
                <p className="mb-3 text-xs text-zinc-500">{es.exams.reviewHint}</p>
                <ul className="space-y-3">
                  {failed.flatMap((q) =>
                    (byId.get(q.id)?.evidence ?? []).map((c) => (
                      <li key={`${q.id}-${c.ref}`} className="text-sm">
                        <blockquote className="border-l-2 border-accent-500 pl-3 whitespace-pre-wrap">
                          {c.text}
                        </blockquote>
                        <button
                          type="button"
                          className="mt-1 text-xs text-accent-700 hover:underline dark:text-accent-100"
                          onClick={() =>
                            navigate({
                              name: 'source',
                              id: c.source_id,
                              at: c.start_ms ?? undefined,
                            })
                          }
                        >
                          {c.source_title} · {es.docs.openSource}
                        </button>
                      </li>
                    )),
                  )}
                </ul>
              </>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
