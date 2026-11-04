import { useEffect, useState } from 'react'
import { Button, Card, ConfirmButton, ErrorText, Loading, PageHeader } from '../components/ui'
import { es } from '../i18n/es'
import { api } from '../lib/api'
import { grade10, isGenerating } from '../lib/exams'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { ExamStatusBadge } from './Exams'

export function ExamView({ id }: { id: string }) {
  const navigate = useNavigate()
  const q = useQuery(() => api.getExam(id), [id])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const e = q.data
  const generating = e ? isGenerating(e) : false
  const { reload } = q
  useEffect(() => {
    if (!generating) return
    const t = window.setInterval(() => reload(), 1500)
    return () => window.clearInterval(t)
  }, [generating, reload])

  if (!e) {
    return (
      <div className="mx-auto max-w-4xl px-10 py-10">
        {q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}
      </div>
    )
  }

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  const start = () =>
    run(async () => {
      const a = await api.startAttempt(e.id)
      navigate({ name: 'attempt', id: a.id })
    })

  const c = e.config
  const summary = [
    es.exams.questionsN(e.status === 'ready' ? e.questions : e.requested),
    c.types.map((t) => es.exams.typeShort[t]).join(' + '),
    es.exams.difficulties[c.difficulty],
    c.mode === 'timed'
      ? `${es.exams.modeShort.timed} (${c.time_limit_min} min)`
      : es.exams.modeShort.practice,
    es.exams.penaltyNote(c.penalty),
  ].join(' · ')

  return (
    <div className="mx-auto max-w-4xl px-10 py-10">
      <button
        type="button"
        className="mb-3 text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: 'exams' })}
      >
        ← {es.exams.title}
      </button>
      <PageHeader
        title={e.title}
        subtitle={`${summary} · ${formatDate(e.created_at)}`}
        actions={
          <ConfirmButton
            label={es.common.delete}
            title={e.title}
            onConfirm={async () => {
              await api.deleteExam(e.id)
              navigate({ name: 'exams' })
            }}
          />
        }
      />
      <ErrorText>{error}</ErrorText>
      <div className="space-y-6">
        {generating && (
          <Card className="space-y-2">
            <div className="flex items-center gap-3">
              <ExamStatusBadge exam={e} />
              <span className="text-sm text-zinc-500">{e.message}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
              <div
                className="h-full bg-accent-600 transition-[width]"
                style={{ width: `${Math.round(e.progress * 100)}%` }}
              />
            </div>
            <p className="text-xs text-zinc-500">{es.exams.generateHint}</p>
          </Card>
        )}
        {e.status === 'insufficient' && (
          <Card className="space-y-3 border-amber-300 dark:border-amber-800">
            <ExamStatusBadge exam={e} />
            <p className="text-sm">{es.exams.insufficient(e.available, e.requested)}</p>
            <p className="text-xs text-zinc-500">{es.exams.insufficientHint}</p>
            <div className="flex gap-2">
              {e.available > 0 && (
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => void run(async () => (await api.acceptExam(e.id), reload()))}
                >
                  {es.exams.acceptFewer(e.available)}
                </Button>
              )}
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await api.deleteExam(e.id)
                    navigate({ name: 'exams' })
                  })
                }
              >
                {es.exams.discard}
              </Button>
            </div>
          </Card>
        )}
        {(e.status === 'failed' || e.status === 'cancelled') && (
          <Card className="space-y-3">
            <ExamStatusBadge exam={e} />
            <ErrorText>{e.error_message}</ErrorText>
            <Button
              disabled={busy}
              onClick={() => void run(async () => (await api.retryExam(e.id), reload()))}
            >
              {es.common.retry}
            </Button>
          </Card>
        )}
        {e.status === 'ready' && (
          <Card className="flex items-center gap-4">
            <div className="flex-1 text-sm text-zinc-600 dark:text-zinc-400">
              {es.exams.validation(e.stats.valid, e.stats.proposed)}
              {e.model ? ` · ${es.docs.model(e.model)}` : ''}
            </div>
            <Button variant="primary" disabled={busy} onClick={() => void start()}>
              {es.exams.start}
            </Button>
          </Card>
        )}
        {e.status === 'ready' && (
          <Card>
            <h2 className="mb-3 font-medium">{es.exams.attempts}</h2>
            {e.attempts.length === 0 ? (
              <p className="text-sm text-zinc-500">{es.exams.noAttempts}</p>
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {e.attempts.map((a) => {
                  const g = grade10(a.score, a.max_score)
                  return (
                    <li key={a.id} className="flex items-center gap-3 py-2 text-sm">
                      <span className="flex-1">{formatDate(a.started_at)}</span>
                      {a.status === 'graded' && g != null && (
                        <span className="font-medium tabular-nums">
                          {g.toLocaleString('es-ES')}/10
                        </span>
                      )}
                      {a.status === 'grading' && (
                        <span className="text-xs text-zinc-500">{es.exams.grading}</span>
                      )}
                      <Button onClick={() => navigate({ name: 'attempt', id: a.id })}>
                        {a.status === 'in_progress' ? es.exams.continue : es.exams.viewResult}
                      </Button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>
        )}
      </div>
    </div>
  )
}
