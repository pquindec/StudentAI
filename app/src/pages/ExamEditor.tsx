import { useState } from 'react'
import { Button, Card, ErrorText, Field, inputClass, Loading, PageHeader } from '../components/ui'
import { es } from '../i18n/es'
import { api, type ManualExam } from '../lib/api'
import {
  type Draft,
  type DraftQuestion,
  emptyDraft,
  emptyQuestion,
  fromManual,
  MAX_OPTIONS,
  MAX_QUESTIONS,
  move,
  PENALTIES,
  type QType,
  removeOption,
  toPayload,
} from '../lib/manualExam'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'

const TYPES: QType[] = ['single', 'true_false', 'short']
const DIFFICULTIES = ['easy', 'medium', 'hard'] as const
type Source = { id: string; title: string }

/** Crear (sin `examId`) o editar un examen con preguntas escritas a mano. */
export function ExamEditor({ subjectId, examId }: { subjectId: string; examId?: string }) {
  const existing = useQuery<ManualExam | null>(
    () => (examId ? api.getManualExam(examId) : Promise.resolve(null)),
    [examId],
  )
  const sources = useQuery(
    () => api.listSources({ subject_id: subjectId, status: 'ready', limit: 200 }),
    [subjectId],
  )
  if (examId && !existing.data) {
    return (
      <div className="mx-auto max-w-4xl px-10 py-10">
        {existing.error ? <ErrorText>{existing.error}</ErrorText> : <Loading />}
      </div>
    )
  }
  return (
    <Editor
      subjectId={subjectId}
      examId={examId}
      initial={existing.data ? fromManual(existing.data) : emptyDraft()}
      editable={existing.data?.editable ?? true}
      sources={sources.data?.items ?? []}
    />
  )
}

function Editor({
  subjectId,
  examId,
  initial,
  editable,
  sources,
}: {
  subjectId: string
  examId?: string
  initial: Draft
  editable: boolean
  sources: Source[]
}) {
  const navigate = useNavigate()
  const [d, setD] = useState<Draft>(initial)
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const back = () => navigate(examId ? { name: 'exam', id: examId } : { name: 'exams' })

  const setQ = (i: number, patch: Partial<DraftQuestion>) =>
    setD((cur) => ({
      ...cur,
      questions: cur.questions.map((q, j) => (j === i ? { ...q, ...patch } : q)),
    }))
  const replaceQ = (i: number, q: DraftQuestion) =>
    setD((cur) => ({ ...cur, questions: cur.questions.map((x, j) => (j === i ? q : x)) }))

  const save = async () => {
    const out = toPayload(d)
    if (!('body' in out)) {
      setErrors(out.errors)
      return
    }
    setErrors([])
    setBusy(true)
    try {
      const exam = examId
        ? await api.updateManualExam(examId, out.body)
        : await api.createManualExam(subjectId, out.body)
      navigate({ name: 'exam', id: exam.id })
    } catch (e) {
      setErrors([errorMessage(e)])
    } finally {
      setBusy(false)
    }
  }
  const duplicate = async () => {
    if (!examId) return
    setBusy(true)
    try {
      const copy = await api.duplicateExam(examId)
      navigate({ name: 'examEditor', subjectId, id: copy.id })
    } catch (e) {
      setErrors([errorMessage(e)])
    } finally {
      setBusy(false)
    }
  }

  if (!editable) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 px-10 py-10">
        <PageHeader title={es.examEditor.editTitle} />
        <Card className="space-y-3">
          <p className="text-sm">{es.examEditor.locked}</p>
          <ErrorText>{errors[0]}</ErrorText>
          <div className="flex gap-2">
            <Button onClick={back}>{es.common.back}</Button>
            <Button variant="primary" disabled={busy} onClick={() => void duplicate()}>
              {es.examEditor.duplicate}
            </Button>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-10 py-10">
      <button type="button" className="mb-3 text-sm text-zinc-500 hover:underline" onClick={back}>
        ← {examId ? es.exams.backToExam : es.exams.title}
      </button>
      <PageHeader
        title={examId ? es.examEditor.editTitle : es.examEditor.newTitle}
        subtitle={es.examEditor.subtitle}
      />
      <div className="space-y-6">
        <Card className="space-y-4">
          <h2 className="font-medium">{es.examEditor.general}</h2>
          <Field label={es.exams.titleField}>
            <input
              className={inputClass}
              value={d.title}
              maxLength={300}
              onChange={(e) => setD({ ...d, title: e.target.value })}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <fieldset className="space-y-1">
              <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                {es.exams.mode}
              </legend>
              {(['practice', 'timed'] as const).map((m) => (
                <label key={m} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="radio"
                    name="mode"
                    checked={d.mode === m}
                    onChange={() => setD({ ...d, mode: m })}
                  />
                  {es.exams.modes[m]}
                </label>
              ))}
              {d.mode === 'timed' && (
                <Field label={es.exams.timeLimit}>
                  <input
                    type="number"
                    min={1}
                    max={240}
                    className={`${inputClass} w-28`}
                    value={d.minutes}
                    onChange={(e) => setD({ ...d, minutes: Number(e.target.value) || 0 })}
                  />
                </Field>
              )}
            </fieldset>
            <Field label={es.exams.penalty}>
              <select
                className={inputClass}
                value={String(d.penalty)}
                onChange={(e) => setD({ ...d, penalty: Number(e.target.value) })}
              >
                {PENALTIES.map((p) => (
                  <option key={p} value={String(p)}>
                    {es.exams.penalties[String(p) as keyof typeof es.exams.penalties]}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </Card>

        {d.questions.map((q, i) => (
          <QuestionCard
            key={q.key}
            q={q}
            n={i + 1}
            total={d.questions.length}
            sources={sources}
            onChange={(patch) => setQ(i, patch)}
            onReplace={(next) => replaceQ(i, next)}
            onMove={(to) => setD({ ...d, questions: move(d.questions, i, to) })}
            onRemove={() => setD({ ...d, questions: d.questions.filter((_, j) => j !== i) })}
          />
        ))}

        <div className="flex flex-wrap gap-2">
          {TYPES.map((t) => (
            <Button
              key={t}
              disabled={d.questions.length >= MAX_QUESTIONS}
              onClick={() => setD({ ...d, questions: [...d.questions, emptyQuestion(t)] })}
            >
              {es.examEditor.add(es.exams.type[t])}
            </Button>
          ))}
        </div>

        {errors.length > 0 && (
          <div role="alert" className="space-y-1 text-sm text-red-600 dark:text-red-400">
            {errors.map((e) => (
              <p key={e}>{e}</p>
            ))}
          </div>
        )}
        <div className="flex items-center justify-end gap-3">
          <span className="text-sm text-zinc-500">{es.examEditor.count(d.questions.length)}</span>
          <Button onClick={back}>{es.common.cancel}</Button>
          <Button variant="primary" disabled={busy} onClick={() => void save()}>
            {busy ? es.common.saving : es.examEditor.save}
          </Button>
        </div>
      </div>
    </div>
  )
}

function QuestionCard({
  q,
  n,
  total,
  sources,
  onChange,
  onReplace,
  onMove,
  onRemove,
}: {
  q: DraftQuestion
  n: number
  total: number
  sources: Source[]
  onChange: (patch: Partial<DraftQuestion>) => void
  onReplace: (q: DraftQuestion) => void
  onMove: (to: number) => void
  onRemove: () => void
}) {
  const E = es.examEditor
  const [more, setMore] = useState(Boolean(q.justification || q.sourceId))
  return (
    <Card className="space-y-4">
      <section aria-label={E.question(n)} className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="flex-1 font-medium">{E.question(n)}</h2>
          <select
            aria-label={es.exams.types}
            className={`${inputClass} w-auto`}
            value={q.type}
            onChange={(e) => onChange({ type: e.target.value as QType })}
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {es.exams.type[t]}
              </option>
            ))}
          </select>
          <Button variant="ghost" disabled={n === 1} onClick={() => onMove(n - 2)}>
            ↑ <span className="sr-only">{E.moveUp}</span>
          </Button>
          <Button variant="ghost" disabled={n === total} onClick={() => onMove(n)}>
            ↓ <span className="sr-only">{E.moveDown}</span>
          </Button>
          <Button variant="ghost" onClick={onRemove}>
            {E.remove}
          </Button>
        </div>

        <Field label={q.type === 'true_false' ? E.stemTf : E.stem}>
          <textarea
            className={`${inputClass} min-h-16`}
            value={q.stem}
            maxLength={2000}
            onChange={(e) => onChange({ stem: e.target.value })}
          />
        </Field>

        {q.type === 'single' && (
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
              {E.options}
            </legend>
            {q.options.map((o, j) => (
              <div key={j} className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`correct-${q.key}`}
                  aria-label={E.correctOption(j + 1)}
                  checked={q.correct === j}
                  onChange={() => onChange({ correct: j })}
                />
                <input
                  aria-label={E.option(j + 1)}
                  className={inputClass}
                  value={o}
                  maxLength={500}
                  onChange={(e) =>
                    onChange({ options: q.options.map((x, k) => (k === j ? e.target.value : x)) })
                  }
                />
                <Button
                  variant="ghost"
                  aria-label={E.removeOption(j + 1)}
                  disabled={q.options.length <= 2}
                  onClick={() => onReplace(removeOption(q, j))}
                >
                  ✕
                </Button>
              </div>
            ))}
            <Button
              disabled={q.options.length >= MAX_OPTIONS}
              onClick={() => onChange({ options: [...q.options, ''] })}
            >
              {E.addOption}
            </Button>
          </fieldset>
        )}

        {q.type === 'true_false' && (
          <fieldset className="flex items-center gap-4">
            <legend className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
              {E.truth}
            </legend>
            {([true, false] as const).map((v) => (
              <label key={String(v)} className="flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name={`truth-${q.key}`}
                  checked={q.truth === v}
                  onChange={() => onChange({ truth: v })}
                />
                {v ? es.exams.trueLabel : es.exams.falseLabel}
              </label>
            ))}
          </fieldset>
        )}

        {q.type === 'short' && (
          <div className="space-y-3">
            <Field label={E.model} hint={E.modelHint}>
              <textarea
                className={`${inputClass} min-h-16`}
                value={q.model}
                maxLength={2000}
                onChange={(e) => onChange({ model: e.target.value })}
              />
            </Field>
            <Field label={`${E.rubric} ${es.common.optional}`}>
              <textarea
                className={`${inputClass} min-h-16`}
                value={q.rubric}
                onChange={(e) => onChange({ rubric: e.target.value })}
              />
            </Field>
          </div>
        )}

        <div>
          <button
            type="button"
            className="text-sm text-zinc-500 hover:underline"
            aria-expanded={more}
            onClick={() => setMore(!more)}
          >
            {more ? '▾' : '▸'} {E.more}
          </button>
          {more && (
            <div className="mt-3 space-y-3">
              <Field label={`${E.justification} ${es.common.optional}`}>
                <textarea
                  className={`${inputClass} min-h-16`}
                  value={q.justification}
                  maxLength={2000}
                  onChange={(e) => onChange({ justification: e.target.value })}
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={es.exams.difficulty}>
                  <select
                    className={inputClass}
                    value={q.difficulty}
                    onChange={(e) =>
                      onChange({ difficulty: e.target.value as DraftQuestion['difficulty'] })
                    }
                  >
                    {DIFFICULTIES.map((x) => (
                      <option key={x} value={x}>
                        {es.exams.difficulties[x]}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={`${E.source} ${es.common.optional}`}>
                  <select
                    className={inputClass}
                    value={q.sourceId}
                    onChange={(e) => onChange({ sourceId: e.target.value })}
                  >
                    <option value="">{E.noSource}</option>
                    {sources.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            </div>
          )}
        </div>
      </section>
    </Card>
  )
}
