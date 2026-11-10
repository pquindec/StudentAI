import { useEffect, useState } from 'react'
import { es } from '../i18n/es'
import type { LiveSession, QuizRank, QuizState } from '../lib/api'
import { QrCode } from './QrCode'
import { Button, Card } from './ui'

const LETTERS = 'ABCDEF'
const MEDALS = ['🥇', '🥈', '🥉']

/** Segundos que quedan, contando desde que llegó el dato (se remonta con cada consulta). */
function Countdown({ ms, className = '' }: { ms: number; className?: string }) {
  const [start] = useState(() => Date.now())
  const [now, setNow] = useState(start)
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(t)
  }, [])
  const left = Math.max(0, Math.ceil((ms - (now - start)) / 1000))
  return <span className={`tabular-nums ${className}`}>{left}</span>
}

function countdownKey(s: LiveSession, q: QuizState) {
  return `${q.phase}:${q.index}:${s.server_now}`
}

export function Leaderboard({ rows, max = 10 }: { rows: QuizRank[]; max?: number }) {
  return (
    <ol className="divide-y divide-zinc-100 dark:divide-zinc-800">
      {rows.slice(0, max).map((r) => (
        <li key={r.participant_id} className="flex items-center gap-3 py-1.5">
          <span className="w-8 font-semibold tabular-nums">
            {MEDALS[r.rank - 1] ?? `${r.rank}.º`}
          </span>
          <span className="min-w-0 flex-1 truncate">{r.name}</span>
          <span className="tabular-nums text-zinc-600 dark:text-zinc-400">
            {es.live.quiz.points(r.score)}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** Resumen del concurso en la sala (la vista grande es el proyector). */
export function QuizPanel({ session: s }: { session: LiveSession }) {
  const q = s.quiz
  if (!q) return null
  const Q = es.live.quiz
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="flex-1 font-medium">{Q.title}</h2>
        <span className="text-sm text-zinc-500">
          {q.index != null && q.phase !== 'finished' && `${Q.question(q.index + 1, q.total)} · `}
          {Q.phase[q.phase]}
          {q.remaining_ms != null && (
            <>
              {' · '}
              <Countdown key={countdownKey(s, q)} ms={q.remaining_ms} /> s
            </>
          )}
        </span>
      </div>
      <p className="text-xs text-zinc-500">
        {Q.howItWorks(q.total, q.question_s)}
        {q.skipped > 0 && ` ${Q.skipped(q.skipped)}`}
      </p>
      {q.question && (q.phase === 'question' || q.phase === 'reveal') && (
        <p className="text-sm">
          <span className="font-medium">{q.question.stem}</span>
          <span className="ml-2 text-zinc-500">{Q.answered(q.answered, q.players)}</span>
        </p>
      )}
      {q.leaderboard.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-medium">
            {q.phase === 'finished' ? Q.final : Q.leaderboard}
          </h3>
          <Leaderboard rows={q.leaderboard} max={q.phase === 'finished' ? 100 : 10} />
        </div>
      )}
    </Card>
  )
}

/** Vista a pantalla completa para proyectar en el aula. La respuesta correcta solo aparece con
 * la pregunta ya cerrada (el backend no la envía antes). */
export function QuizProjector({
  session: s,
  onClose,
  onNext,
  busy = false,
}: {
  session: LiveSession
  onClose: () => void
  onNext?: () => void // «Pasar ya», con el concurso en marcha
  busy?: boolean
}) {
  const q = s.quiz
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  if (!q) return null
  const Q = es.live.quiz
  const top3 = q.leaderboard.filter((r) => r.rank <= 3)

  let body
  if (q.phase === 'lobby') {
    body = (
      <div className="grid flex-1 items-center gap-10 md:grid-cols-[auto_1fr]">
        <div className="flex flex-col items-center gap-3">
          {s.qr && <QrCode rows={s.qr} label={es.live.scan} className="max-w-[min(60vh,28rem)]" />}
          <p className="text-2xl font-semibold">{Q.joinAt}</p>
        </div>
        <div className="space-y-6">
          {s.url && <p className="text-3xl font-semibold break-all">{s.url}</p>}
          <p className="text-xl">
            {es.live.code}: <span className="font-mono text-4xl tracking-widest">{s.code}</span>
          </p>
          <p className="text-2xl text-zinc-500">{q.players ? Q.players(q.players) : Q.waiting}</p>
          <ul className="flex flex-wrap gap-2">
            {q.leaderboard.map((r) => (
              <li
                key={r.participant_id}
                className="rounded-full bg-zinc-100 px-4 py-1.5 text-xl dark:bg-zinc-800"
              >
                {r.name}
              </li>
            ))}
          </ul>
        </div>
      </div>
    )
  } else if (q.phase === 'countdown') {
    body = (
      <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
        <p className="text-3xl text-zinc-500">
          {q.index != null && Q.question(q.index + 1, q.total)}
        </p>
        <p className="text-5xl font-bold">{Q.ready}</p>
        <Countdown
          key={countdownKey(s, q)}
          ms={q.remaining_ms ?? 0}
          className="text-9xl font-black"
        />
      </div>
    )
  } else if ((q.phase === 'question' || q.phase === 'reveal') && q.question) {
    const reveal = q.phase === 'reveal'
    const most = Math.max(1, ...(q.counts ?? [0]))
    body = (
      <div className={`grid flex-1 gap-8 ${reveal ? 'lg:grid-cols-[1fr_22rem]' : ''}`}>
        <div className="flex flex-col gap-8">
          <div className="flex items-start gap-6">
            <p className="flex-1 text-4xl leading-tight font-bold">{q.question.stem}</p>
            {!reveal && (
              <Countdown
                key={countdownKey(s, q)}
                ms={q.remaining_ms ?? 0}
                className="grid size-28 shrink-0 place-items-center rounded-full border-4 border-accent-500 text-5xl font-black"
              />
            )}
          </div>
          <ul className="grid gap-4 md:grid-cols-2">
            {q.question.options.map((o, i) => {
              const right = reveal && i === q.correct_index
              const faded = reveal && !right
              return (
                <li
                  key={i}
                  className={`flex items-center gap-4 rounded-2xl border-4 p-5 text-3xl font-semibold ${
                    right
                      ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40'
                      : 'border-zinc-200 dark:border-zinc-700'
                  } ${faded ? 'opacity-50' : ''}`}
                >
                  <span
                    className={`grid size-14 shrink-0 place-items-center rounded-full text-white ${right ? 'bg-emerald-600' : 'bg-accent-600'}`}
                  >
                    {right ? '✓' : LETTERS[i]}
                  </span>
                  <span className="min-w-0 flex-1">{o}</span>
                  {reveal && q.counts && (
                    <span className="flex w-28 shrink-0 items-center gap-2 text-xl tabular-nums">
                      <span
                        className="h-3 rounded bg-zinc-400"
                        style={{ width: `${(q.counts[i] / most) * 4}rem` }}
                      />
                      {q.counts[i]}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
          <p className="text-2xl text-zinc-500">
            {reveal && q.answered === 0 ? Q.noAnswers : Q.answered(q.answered, q.players)}
          </p>
        </div>
        {reveal && (
          <div className="text-2xl">
            <h2 className="mb-3 font-bold">{Q.leaderboard}</h2>
            <Leaderboard rows={q.leaderboard} max={5} />
          </div>
        )}
      </div>
    )
  } else {
    // Podio: 2.º · 1.º · 3.º
    const order = [top3[1], top3[0], top3[2]]
    const heights = ['h-40', 'h-56', 'h-28']
    body = (
      <div className="flex flex-1 flex-col items-center justify-center gap-10">
        {top3[0] && <p className="text-6xl font-black">{Q.winner(top3[0].name)}</p>}
        <div className="flex items-end gap-6">
          {order.map((r, i) =>
            r ? (
              <div key={r.participant_id} className="flex w-56 flex-col items-center gap-2">
                <span className="text-6xl">{MEDALS[r.rank - 1]}</span>
                <span className="max-w-full truncate text-3xl font-bold">{r.name}</span>
                <span className="text-2xl text-zinc-500">{Q.points(r.score)}</span>
                <div
                  className={`w-full rounded-t-2xl bg-accent-600 ${heights[i]} grid place-items-center text-5xl font-black text-white`}
                >
                  {r.rank}
                </div>
              </div>
            ) : (
              <div key={i} className="w-56" />
            ),
          )}
        </div>
        {q.leaderboard.length > 3 && (
          <div className="w-full max-w-xl text-2xl">
            <Leaderboard rows={q.leaderboard.slice(3)} max={7} />
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={es.live.quiz.project}
      className="fixed inset-0 z-50 flex flex-col gap-6 overflow-auto bg-white p-10 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100"
    >
      <div className="flex items-center gap-4">
        <h1 className="flex-1 truncate text-2xl font-semibold text-zinc-500">{s.exam_title}</h1>
        {q.phase !== 'lobby' && q.phase !== 'finished' && (
          <span className="text-xl text-zinc-500">{Q.players(q.players)}</span>
        )}
        {onNext && s.status === 'running' && (
          <Button disabled={busy} title={Q.nextHint} onClick={onNext}>
            {Q.next}
          </Button>
        )}
        <Button onClick={onClose}>{Q.exitProject}</Button>
      </div>
      {body}
    </div>
  )
}
