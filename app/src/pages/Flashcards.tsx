import { useCloudConsent } from '../components/CloudConsent'
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
import { api, type Deck } from '../lib/api'
import { isDeckGenerating } from '../lib/flashcards'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { unitTree } from '../lib/subjects'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Checklist } from './Exams'

const NEW_PER_DAY = [5, 10, 20, 30, 50]

export function DeckStatusBadge({ deck }: { deck: Pick<Deck, 'status'> }) {
  const tone =
    deck.status === 'ready'
      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'
      : deck.status === 'failed' || deck.status === 'cancelled'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'
        : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>
      {es.flashcards.status[deck.status]}
    </span>
  )
}

/** Reparto nuevas / aprendiendo / dominadas: barra apilada con etiqueta y número visibles. */
export function CardMix({
  counts,
}: {
  counts: { new: number; learning: number; mastered: number }
}) {
  const parts = [
    { key: 'new', n: counts.new, color: 'var(--series-1)' },
    { key: 'learning', n: counts.learning, color: 'var(--series-2)' },
    { key: 'mastered', n: counts.mastered, color: 'var(--series-3)' },
  ] as const
  const total = parts.reduce((a, p) => a + p.n, 0)
  if (!total) return null
  return (
    <div className="space-y-1.5">
      <div className="flex h-2 gap-[2px] overflow-hidden rounded">
        {parts
          .filter((p) => p.n > 0)
          .map((p) => (
            <div
              key={p.key}
              title={`${es.flashcards.counts[p.key]}: ${p.n}`}
              style={{ width: `${(p.n / total) * 100}%`, background: p.color }}
            />
          ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600 dark:text-zinc-400">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span className="size-2 rounded-sm" style={{ background: p.color }} />
            {es.flashcards.counts[p.key]}{' '}
            <span className="font-medium text-zinc-900 tabular-nums dark:text-zinc-100">{p.n}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function NewDeckDialog({
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
  const [count, setCount] = useState(20)
  const [sourceIds, setSourceIds] = useState<string[]>([])
  const [unitIds, setUnitIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const usable = sources.data?.items.filter((s) => s.version != null) ?? []
  const units = subject.data ? unitTree(subject.data.units) : []

  const askCloud = useCloudConsent()

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      // Solo lo que se ve marcado en esta asignatura.
      const scope = {
        source_ids: sourceIds.filter((id) => usable.some((s) => s.id === id)),
        unit_ids: unitIds.filter((id) => units.some((u) => u.unit.id === id)),
        exclude_source_ids: [],
      }
      const consent = await askCloud({ kind: 'deck', subject_id: subjectId, scope, count })
      if (consent === false) return
      const deck = await api.createDeck(subjectId, {
        title: title.trim() || null,
        count,
        scope,
        consent_id: consent,
      })
      onClose()
      navigate({ name: 'deck', id: deck.id })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} title={es.flashcards.newDeck} onClose={onClose}>
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <Field label={es.flashcards.count}>
          <input
            type="number"
            min={5}
            max={100}
            className={`${inputClass} w-28`}
            value={count}
            onChange={(e) => setCount(Math.min(100, Math.max(5, Number(e.target.value) || 5)))}
          />
        </Field>
        {units.length > 0 && (
          <fieldset>
            <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
              {es.flashcards.topics} · {unitIds.length ? '' : es.flashcards.allTopics}
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
            {es.flashcards.sources} · {sourceIds.length ? '' : es.flashcards.allSources}
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
        <Field label={`${es.flashcards.titleField} ${es.common.optional}`}>
          <input
            className={inputClass}
            value={title}
            maxLength={300}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <p className="text-xs text-zinc-500">{es.flashcards.generateHint}</p>
        <ErrorText>{error}</ErrorText>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>{es.common.cancel}</Button>
        <Button variant="primary" disabled={busy} onClick={() => void submit()}>
          {es.flashcards.generate}
        </Button>
      </div>
    </Modal>
  )
}

export function Flashcards() {
  const navigate = useNavigate()
  const subjects = useQuery(() => api.listSubjects(false), [])
  const [picked, setPicked] = useState('')
  const subjectId = picked || subjects.data?.[0]?.id || ''
  const decks = useQuery(
    () => (subjectId ? api.listDecks(subjectId) : Promise.resolve([])),
    [subjectId],
  )
  const study = useQuery(
    () => (subjectId ? api.study({ subject_id: subjectId }) : Promise.resolve(null)),
    [subjectId, decks.data],
  )
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const busy = decks.data?.some(isDeckGenerating)
  const { reload } = decks
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => reload(), 2000)
    return () => window.clearInterval(t)
  }, [busy, reload])
  const pending = study.data ? study.data.learning + study.data.review + study.data.new : 0

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <PageHeader
        title={es.flashcards.title}
        subtitle={es.flashcards.subtitle}
        actions={
          subjectId ? (
            <div className="flex gap-2">
              <Button
                variant="primary"
                disabled={!pending}
                onClick={() => navigate({ name: 'review', subjectId })}
              >
                {es.flashcards.studyNow(pending)}
              </Button>
              <Button onClick={() => setOpen(true)}>{es.flashcards.newDeck}</Button>
            </div>
          ) : undefined
        }
      />
      <Card className="space-y-4">
        {subjects.data?.length === 0 ? (
          <p className="text-sm">{es.flashcards.needSubject}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-4">
              <Field label={es.flashcards.subject}>
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
              {study.data && (
                <Field label={es.flashcards.newPerDay}>
                  <select
                    className={`${inputClass} w-auto`}
                    value={study.data.new_per_day}
                    onChange={(e) => {
                      setError(null)
                      api
                        .updateStudySettings({ new_per_day: Number(e.target.value) })
                        .then(() => study.reload())
                        .catch((err: unknown) => setError(errorMessage(err)))
                    }}
                  >
                    {[...new Set([...NEW_PER_DAY, study.data.new_per_day])]
                      .sort((a, b) => a - b)
                      .map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                  </select>
                </Field>
              )}
            </div>
            <ErrorText>{error ?? decks.error ?? subjects.error}</ErrorText>
            {!decks.data ? (
              <Loading />
            ) : decks.data.length === 0 ? (
              <p className="text-sm text-zinc-500">{es.flashcards.empty}</p>
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {decks.data.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => navigate({ name: 'deck', id: d.id })}
                      className="flex w-full flex-col gap-2 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900"
                    >
                      <div className="flex w-full items-center gap-3 text-sm">
                        <span className="min-w-0 flex-1 truncate font-medium">{d.title}</span>
                        {d.status === 'ready' && (
                          <span className="text-xs text-zinc-500">
                            {es.flashcards.cardsN(d.counts.total)} ·{' '}
                            {es.flashcards.dueN(d.counts.due)}
                          </span>
                        )}
                        <span className="text-xs text-zinc-500">{formatDate(d.created_at)}</span>
                        <DeckStatusBadge deck={d} />
                      </div>
                      {d.status === 'ready' && <CardMix counts={d.counts} />}
                      {isDeckGenerating(d) && d.message && (
                        <span className="text-xs text-zinc-500">{d.message}</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Card>
      {/* Se monta al abrir (y por asignatura): no arrastra lo marcado en otra asignatura. */}
      {subjectId && open && (
        <NewDeckDialog key={subjectId} open subjectId={subjectId} onClose={() => setOpen(false)} />
      )}
    </div>
  )
}
