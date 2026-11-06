import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  ConfirmButton,
  ErrorText,
  Field,
  inputClass,
  Loading,
  Modal,
  PageHeader,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, type Flashcard } from '../lib/api'
import { isDeckGenerating } from '../lib/flashcards'
import { formatDate, formatDay, formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { CardMix, DeckStatusBadge } from './Flashcards'

function Evidence({ card }: { card: Flashcard }) {
  const navigate = useNavigate()
  const ev = card.evidence
  if (!ev) return <p className="text-xs text-zinc-500">{es.flashcards.noEvidence}</p>
  const where =
    ev.start_ms != null
      ? formatDuration(ev.start_ms)
      : ev.page != null
        ? es.docs.page(ev.page)
        : null
  return (
    <div className="space-y-1">
      <blockquote className="border-l-2 border-accent-500 pl-3 text-xs whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">
        {ev.text}
      </blockquote>
      <button
        type="button"
        className="text-xs text-accent-700 hover:underline dark:text-accent-300"
        onClick={() => navigate({ name: 'source', id: ev.source_id, at: ev.start_ms ?? undefined })}
      >
        {ev.source_title}
        {where ? ` · ${where}` : ''}
      </button>
    </div>
  )
}

function EditCard({
  card,
  onClose,
  onSaved,
}: {
  card: Flashcard
  onClose: () => void
  onSaved: () => void
}) {
  const [front, setFront] = useState(card.front)
  const [back, setBack] = useState(card.back)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.updateCard(card.id, { front: front.trim(), back: back.trim() })
      onSaved()
      onClose()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open title={es.flashcards.edit} onClose={onClose}>
      <div className="space-y-3">
        <Field label={es.flashcards.front}>
          <textarea
            className={`${inputClass} h-20`}
            maxLength={1000}
            value={front}
            onChange={(e) => setFront(e.target.value)}
          />
        </Field>
        <Field label={es.flashcards.back}>
          <textarea
            className={`${inputClass} h-28`}
            maxLength={2000}
            value={back}
            onChange={(e) => setBack(e.target.value)}
          />
        </Field>
        <ErrorText>{error}</ErrorText>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>{es.common.cancel}</Button>
        <Button
          variant="primary"
          disabled={busy || !front.trim() || !back.trim()}
          onClick={() => void save()}
        >
          {busy ? es.common.saving : es.common.save}
        </Button>
      </div>
    </Modal>
  )
}

function CardRow({ card, onChanged }: { card: Flashcard; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const state = card.mastered ? es.flashcards.mastered : es.flashcards.state[card.state]
  const toggle = () => {
    setError(null)
    api
      .updateCard(card.id, { suspended: !card.suspended })
      .then(onChanged)
      .catch((e: unknown) => setError(errorMessage(e)))
  }
  return (
    <li className={`space-y-2 py-3 ${card.suspended ? 'opacity-60' : ''}`}>
      <div className="flex gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm font-medium">{card.front}</p>
          <p className="text-sm text-zinc-700 dark:text-zinc-300">{card.back}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 text-xs text-zinc-500">
          <span>
            {card.suspended ? es.flashcards.suspended : state}
            {card.edited ? ` · ${es.flashcards.edited}` : ''}
          </span>
          {card.state !== 'new' && !card.suspended && (
            <span>{es.flashcards.due(formatDay(card.due_at))}</span>
          )}
        </div>
      </div>
      <Evidence card={card} />
      <div className="flex flex-wrap gap-1">
        <Button variant="ghost" onClick={() => setEditing(true)}>
          {es.common.edit}
        </Button>
        <Button variant="ghost" onClick={toggle}>
          {card.suspended ? es.flashcards.unsuspend : es.flashcards.suspend}
        </Button>
        <ConfirmButton
          label={es.common.delete}
          title={es.flashcards.deleteCard}
          body={card.front}
          onConfirm={async () => {
            await api.deleteCard(card.id)
            onChanged()
          }}
        />
      </div>
      <ErrorText>{error}</ErrorText>
      {editing && <EditCard card={card} onClose={() => setEditing(false)} onSaved={onChanged} />}
    </li>
  )
}

export function DeckView({ id }: { id: string }) {
  const navigate = useNavigate()
  const q = useQuery(() => api.getDeck(id), [id])
  const [error, setError] = useState<string | null>(null)
  const d = q.data
  const generating = d ? isDeckGenerating(d) : false
  const { reload } = q
  useEffect(() => {
    if (!generating) return
    const t = window.setInterval(() => reload(), 1500)
    return () => window.clearInterval(t)
  }, [generating, reload])

  if (!d) {
    return (
      <div className="mx-auto max-w-4xl px-10 py-10">
        {q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-10 py-10">
      <button
        type="button"
        className="mb-3 text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: 'flashcards' })}
      >
        ← {es.flashcards.title}
      </button>
      <PageHeader
        title={d.title}
        subtitle={`${es.flashcards.cardsN(d.status === 'ready' ? d.counts.total : d.requested)} · ${formatDate(d.created_at)}`}
        actions={
          <ConfirmButton
            label={es.common.delete}
            title={d.title}
            onConfirm={async () => {
              await api.deleteDeck(d.id)
              navigate({ name: 'flashcards' })
            }}
          />
        }
      />
      <ErrorText>{error}</ErrorText>
      <div className="space-y-6">
        {generating && (
          <Card className="space-y-2">
            <div className="flex items-center gap-3">
              <DeckStatusBadge deck={d} />
              <span className="text-sm text-zinc-500">{d.message}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
              <div
                className="h-full bg-accent-600 transition-[width]"
                style={{ width: `${Math.round(d.progress * 100)}%` }}
              />
            </div>
            <p className="text-xs text-zinc-500">{es.flashcards.generateHint}</p>
          </Card>
        )}
        {(d.status === 'failed' || d.status === 'cancelled') && (
          <Card className="space-y-3">
            <DeckStatusBadge deck={d} />
            <ErrorText>{d.error_message}</ErrorText>
            <Button
              onClick={() => {
                setError(null)
                api
                  .retryDeck(d.id)
                  .then(() => reload())
                  .catch((e: unknown) => setError(errorMessage(e)))
              }}
            >
              {es.common.retry}
            </Button>
          </Card>
        )}
        {d.status === 'ready' && (
          <Card className="space-y-3">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex-1 text-sm text-zinc-600 dark:text-zinc-400">
                {es.flashcards.dueN(d.counts.due + d.counts.new)}
                {d.counts.next_due_at && !d.counts.due
                  ? ` · ${es.flashcards.nextDue(formatDate(d.counts.next_due_at))}`
                  : ''}
              </div>
              <Button
                variant="primary"
                onClick={() =>
                  navigate({ name: 'review', deckId: d.id, back: { name: 'deck', id: d.id } })
                }
              >
                {es.flashcards.studyDeck}
              </Button>
            </div>
            <CardMix counts={d.counts} />
            {d.stats.saved < d.requested && (
              <p className="text-sm text-amber-700 dark:text-amber-400">
                {es.flashcards.fewer(d.stats.saved, d.requested)}
              </p>
            )}
            <p className="text-xs text-zinc-500">
              {es.flashcards.masteredHint} ·{' '}
              {es.flashcards.validation(d.stats.saved, d.stats.proposed)}
              {d.model ? ` · ${es.docs.model(d.model)}` : ''}
            </p>
          </Card>
        )}
        {d.status === 'ready' && (
          <Card>
            <h2 className="font-medium">{es.flashcards.cards}</h2>
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {d.cards.map((c) => (
                <CardRow key={c.id} card={c} onChanged={reload} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  )
}
