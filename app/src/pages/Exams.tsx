import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  ErrorText,
  Field,
  inputClass,
  Loading,
  Modal,
  PageHeader,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, type Exam, type ExamConfig } from '../lib/api'
import { isGenerating, grade10 } from '../lib/exams'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { unitTree } from '../lib/subjects'
import { errorMessage, useQuery } from '../lib/useQuery'

type QType = ExamConfig['types'][number]
const TYPES: QType[] = ['single', 'true_false', 'short']
const PENALTIES = ['0', '0.25', '0.33', '0.5'] as const

export function ExamStatusBadge({ exam }: { exam: Pick<Exam, 'status'> }) {
  const tone =
    exam.status === 'ready'
      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'
      : exam.status === 'failed' || exam.status === 'cancelled'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : exam.status === 'insufficient'
          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
          : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>
      {es.exams.status[exam.status]}
    </span>
  )
}

function Checklist({
  items,
  picked,
  onChange,
}: {
  items: { id: string; label: string; depth?: number }[]
  picked: string[]
  onChange: (ids: string[]) => void
}) {
  return (
    <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto rounded-md border border-zinc-200 p-2 dark:border-zinc-800">
      {items.map((it) => (
        <li key={it.id} style={{ paddingLeft: `${(it.depth ?? 0) * 0.9}rem` }}>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(it.id)}
              onChange={() =>
                onChange(
                  picked.includes(it.id) ? picked.filter((x) => x !== it.id) : [...picked, it.id],
                )
              }
            />
            <span className="truncate">{it.label}</span>
          </label>
        </li>
      ))}
    </ul>
  )
}

function NewExamDialog({
  open,
  subjectId,
  onClose,
}: {
  open: boolean
  subjectId: string
  onClose: () => void
}) {
  const navigate = useNavigate()
  const sources = useQuery(
    () =>
      open
        ? api.listSources({ subject_id: subjectId, status: 'ready', limit: 200 })
        : Promise.resolve(null),
    [open, subjectId],
  )
  const subject = useQuery(
    () => (open ? api.getSubject(subjectId) : Promise.resolve(null)),
    [open, subjectId],
  )
  const [title, setTitle] = useState('')
  const [count, setCount] = useState(10)
  const [types, setTypes] = useState<QType[]>(['single', 'true_false'])
  const [difficulty, setDifficulty] = useState<ExamConfig['difficulty']>('mixed')
  const [options, setOptions] = useState(4)
  const [mode, setMode] = useState<ExamConfig['mode']>('practice')
  const [minutes, setMinutes] = useState(20)
  const [penalty, setPenalty] = useState<(typeof PENALTIES)[number]>('0')
  const [sourceIds, setSourceIds] = useState<string[]>([])
  const [unitIds, setUnitIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const usable = sources.data?.items.filter((s) => s.version != null) ?? []
  const units = subject.data ? unitTree(subject.data.units) : []

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const exam = await api.createExam(subjectId, {
        title: title.trim() || null,
        config: {
          count,
          types,
          difficulty,
          options,
          mode,
          time_limit_min: mode === 'timed' ? minutes : null,
          penalty: Number(penalty),
        },
        scope: { source_ids: sourceIds, unit_ids: unitIds, exclude_source_ids: [] },
      })
      onClose()
      navigate({ name: 'exam', id: exam.id })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} title={es.exams.new} onClose={onClose}>
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <div className="grid grid-cols-2 gap-3">
          <Field label={es.exams.count}>
            <input
              type="number"
              min={1}
              max={50}
              className={inputClass}
              value={count}
              onChange={(e) => setCount(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
            />
          </Field>
          <Field label={es.exams.difficulty}>
            <select
              className={inputClass}
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value as ExamConfig['difficulty'])}
            >
              {(Object.keys(es.exams.difficulties) as ExamConfig['difficulty'][]).map((d) => (
                <option key={d} value={d}>
                  {es.exams.difficulties[d]}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <fieldset>
          <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {es.exams.types}
          </legend>
          <div className="mt-1 flex flex-wrap gap-4">
            {TYPES.map((t) => (
              <label key={t} className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={types.includes(t)}
                  onChange={() =>
                    setTypes((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))
                  }
                />
                {es.exams.type[t]}
              </label>
            ))}
          </div>
          {types.includes('short') && (
            <p className="mt-1 text-xs text-zinc-500">{es.exams.shortHint}</p>
          )}
        </fieldset>
        <div className="grid grid-cols-2 gap-3">
          {types.includes('single') && (
            <Field label={es.exams.options}>
              <select
                className={inputClass}
                value={options}
                onChange={(e) => setOptions(Number(e.target.value))}
              >
                {[3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={es.exams.penalty}>
            <select
              className={inputClass}
              value={penalty}
              onChange={(e) => setPenalty(e.target.value as (typeof PENALTIES)[number])}
            >
              {PENALTIES.map((p) => (
                <option key={p} value={p}>
                  {es.exams.penalties[p]}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <fieldset className="space-y-1">
          <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {es.exams.mode}
          </legend>
          {(['practice', 'timed'] as const).map((m) => (
            <label key={m} className="flex items-center gap-1.5 text-sm">
              <input type="radio" name="mode" checked={mode === m} onChange={() => setMode(m)} />
              {es.exams.modes[m]}
            </label>
          ))}
          {mode === 'timed' && (
            <Field label={es.exams.timeLimit}>
              <input
                type="number"
                min={1}
                max={240}
                className={`${inputClass} w-28`}
                value={minutes}
                onChange={(e) =>
                  setMinutes(Math.min(240, Math.max(1, Number(e.target.value) || 1)))
                }
              />
            </Field>
          )}
        </fieldset>
        {units.length > 0 && (
          <fieldset>
            <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
              {es.exams.topics} · {unitIds.length ? '' : es.exams.allTopics}
            </legend>
            <Checklist
              items={units.map((u) => ({ id: u.unit.id, label: u.unit.title, depth: u.depth }))}
              picked={unitIds}
              onChange={setUnitIds}
            />
          </fieldset>
        )}
        <fieldset>
          <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {es.exams.sources} · {sourceIds.length ? '' : es.exams.allSources}
          </legend>
          {sources.loading && !sources.data ? (
            <Loading />
          ) : (
            <Checklist
              items={usable.map((s) => ({ id: s.id, label: s.title }))}
              picked={sourceIds}
              onChange={setSourceIds}
            />
          )}
        </fieldset>
        <Field label={`${es.exams.titleField} ${es.common.optional}`}>
          <input
            className={inputClass}
            value={title}
            maxLength={300}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <p className="text-xs text-zinc-500">{es.exams.generateHint}</p>
        <ErrorText>{error}</ErrorText>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>{es.common.cancel}</Button>
        <Button
          variant="primary"
          disabled={busy || types.length === 0}
          onClick={() => void submit()}
        >
          {es.exams.generate}
        </Button>
      </div>
    </Modal>
  )
}

export function Exams() {
  const navigate = useNavigate()
  const subjects = useQuery(() => api.listSubjects(false), [])
  const [picked, setPicked] = useState('')
  const subjectId = picked || subjects.data?.[0]?.id || ''
  const exams = useQuery(
    () => (subjectId ? api.listExams(subjectId) : Promise.resolve([])),
    [subjectId],
  )
  const [open, setOpen] = useState(false)
  const busy = exams.data?.some(isGenerating)
  const { reload } = exams
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => reload(), 2000)
    return () => window.clearInterval(t)
  }, [busy, reload])

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <PageHeader
        title={es.exams.title}
        subtitle={es.exams.subtitle}
        actions={
          subjectId ? (
            <Button variant="primary" onClick={() => setOpen(true)}>
              {es.exams.new}
            </Button>
          ) : undefined
        }
      />
      <Card className="space-y-4">
        {subjects.data?.length === 0 ? (
          <p className="text-sm">{es.exams.needSubject}</p>
        ) : (
          <>
            <Field label={es.exams.subject}>
              <select
                className={`${inputClass} w-auto`}
                value={subjectId}
                onChange={(e) => setPicked(e.target.value)}
              >
                {subjects.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            <ErrorText>{exams.error ?? subjects.error}</ErrorText>
            {!exams.data ? (
              <Loading />
            ) : exams.data.length === 0 ? (
              <p className="text-sm text-zinc-500">{es.exams.empty}</p>
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {exams.data.map((e) => {
                  const best = e.attempts
                    .map((a) => grade10(a.score, a.max_score))
                    .filter((g): g is number => g != null)
                  return (
                    <li key={e.id}>
                      <button
                        type="button"
                        onClick={() => navigate({ name: 'exam', id: e.id })}
                        className="flex w-full items-center gap-3 py-2.5 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-900"
                      >
                        <span className="min-w-0 flex-1 truncate font-medium">{e.title}</span>
                        <span className="text-xs text-zinc-500">
                          {es.exams.questionsN(e.status === 'ready' ? e.questions : e.requested)}
                          {' · '}
                          {es.exams.modeShort[e.config.mode]}
                        </span>
                        {best.length > 0 && (
                          <span className="text-xs font-medium tabular-nums">
                            {Math.max(...best).toLocaleString('es-ES')}/10
                          </span>
                        )}
                        <span className="text-xs text-zinc-500">{formatDate(e.created_at)}</span>
                        <ExamStatusBadge exam={e} />
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </>
        )}
      </Card>
      {subjectId && (
        <NewExamDialog open={open} subjectId={subjectId} onClose={() => setOpen(false)} />
      )}
    </div>
  )
}
