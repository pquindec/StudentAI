import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Card, ErrorText, Loading } from '../components/ui'
import { es } from '../i18n/es'
import { api, type Rating } from '../lib/api'
import { formatInterval, ratingFromKey } from '../lib/flashcards'
import { formatDate, formatDuration } from '../lib/format'
import { type Route, useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'

const TONE: Record<Rating, string> = {
  1: 'border-red-300 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950',
  2: 'border-amber-300 hover:bg-amber-50 dark:border-amber-800 dark:hover:bg-amber-950',
  3: 'border-emerald-300 hover:bg-emerald-50 dark:border-emerald-800 dark:hover:bg-emerald-950',
  4: 'border-sky-300 hover:bg-sky-50 dark:border-sky-800 dark:hover:bg-sky-950',
}

export function Review({
  subjectId,
  deckId,
  back,
}: {
  subjectId?: string
  deckId?: string
  back?: Route
}) {
  const navigate = useNavigate()
  const q = useQuery(
    () => api.study({ subject_id: subjectId, deck_id: deckId }),
    [subjectId, deckId],
  )
  const [shownFor, setShownFor] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(0)
  const started = useRef(0)
  const s = q.data
  const card = s?.card ?? null
  const cardId = card?.id
  const shown = cardId != null && shownFor === cardId
  const show = useCallback(() => setShownFor(cardId ?? null), [cardId])

  // El tiempo cuenta desde que aparece la tarjeta.
  useEffect(() => {
    started.current = performance.now()
  }, [cardId])

  const rate = useCallback(
    async (rating: Rating) => {
      if (!cardId || busy) return
      setBusy(true)
      setError(null)
      try {
        await api.reviewCard(cardId, rating, Math.round(performance.now() - started.current))
        setDone((n) => n + 1)
        q.reload()
      } catch (e) {
        setError(errorMessage(e))
      } finally {
        setBusy(false)
      }
    },
    [cardId, busy, q],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!cardId || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.target instanceof HTMLElement && e.target.closest('input, textarea, select')) return
      if (e.key === ' ' && !shown) {
        e.preventDefault()
        show()
        return
      }
      const r = shown ? ratingFromKey(e.key) : null
      if (r) {
        e.preventDefault()
        void rate(r)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cardId, shown, rate, show])

  const exit = () => navigate(back ?? { name: 'flashcards' })
  const ev = card?.evidence
  const where =
    ev?.start_ms != null
      ? formatDuration(ev.start_ms)
      : ev?.page != null
        ? es.docs.page(ev.page)
        : null

  return (
    <div className="mx-auto max-w-3xl px-10 py-10">
      <div className="mb-6 flex items-center gap-3">
        <button type="button" className="text-sm text-zinc-500 hover:underline" onClick={exit}>
          ← {es.review.back}
        </button>
        <span className="flex-1" />
        {s && card && (
          <span className="text-xs text-zinc-500 tabular-nums">
            {es.review.remaining(s.learning, s.review, s.new)}
          </span>
        )}
      </div>
      <ErrorText>{error ?? q.error}</ErrorText>
      {!s ? (
        <Loading />
      ) : !card ? (
        <Card className="space-y-3 text-center">
          <h1 className="text-xl font-semibold">{es.review.done}</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{es.review.doneBody(done)}</p>
          {s.next_due_at && (
            <p className="text-sm text-zinc-500">{es.review.nextAt(formatDate(s.next_due_at))}</p>
          )}
          <Button onClick={exit}>{es.common.back}</Button>
        </Card>
      ) : (
        <div className="space-y-4">
          <Card className="space-y-6 py-8">
            <p className="text-center text-lg font-medium whitespace-pre-wrap">{card.front}</p>
            {shown && (
              <>
                <hr className="border-zinc-200 dark:border-zinc-800" />
                <p className="text-center whitespace-pre-wrap">{card.back}</p>
                {ev ? (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-zinc-500">{es.review.evidence}</p>
                    <blockquote className="border-l-2 border-accent-500 pl-3 text-sm whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">
                      {ev.text}
                    </blockquote>
                    <button
                      type="button"
                      className="text-xs text-accent-700 hover:underline dark:text-accent-300"
                      onClick={() =>
                        navigate({ name: 'source', id: ev.source_id, at: ev.start_ms ?? undefined })
                      }
                    >
                      {ev.source_title}
                      {where ? ` · ${where}` : ''}
                    </button>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-500">{es.flashcards.noEvidence}</p>
                )}
              </>
            )}
          </Card>
          {!shown ? (
            <div className="flex justify-center">
              <Button variant="primary" onClick={show}>
                {es.review.show}{' '}
                <span className="ml-2 text-xs opacity-70">{es.review.showKey}</span>
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {s.intervals.map((i) => (
                <button
                  key={i.rating}
                  type="button"
                  disabled={busy}
                  onClick={() => void rate(i.rating)}
                  className={`flex flex-col items-center gap-0.5 rounded-lg border px-2 py-2 text-sm disabled:opacity-50 ${TONE[i.rating]}`}
                >
                  <span className="font-medium">{es.review.ratings[i.rating]}</span>
                  <span className="text-xs text-zinc-500 tabular-nums">
                    {formatInterval(i.seconds)} · {i.rating}
                  </span>
                </button>
              ))}
            </div>
          )}
          <p className="text-center text-xs text-zinc-500">{es.review.keysHint}</p>
        </div>
      )}
    </div>
  )
}
