import { useEffect, useState } from 'react'
import { CitationPanel } from '../components/Citations'
import { CopyButton } from '../components/CopyButton'
import { QrCode } from '../components/QrCode'
import { QuizPanel, QuizProjector } from '../components/Quiz'
import { Button, Card, ConfirmButton, ErrorText, Loading, PageHeader } from '../components/ui'
import { es } from '../i18n/es'
import {
  api,
  type LiveParticipant,
  type LiveQuestionStat,
  type LiveResultRow,
  type LiveSession,
  native,
  nativeError,
} from '../lib/api'
import { formatRemaining, grade10 } from '../lib/exams'
import { classAverage, participantState, resultsCsv } from '../lib/live'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'

const POLL_MS = 1500
const QUIZ_POLL_MS = 1000 // concurso en marcha: el proyector sigue el ritmo de las preguntas

/** Acceso por internet con Cloudflare, con consentimiento en cada activación. */
function TunnelControl({
  session: s,
  busy,
  run,
}: {
  session: LiveSession
  busy: boolean
  run: (fn: () => Promise<unknown>) => Promise<void>
}) {
  const T = es.live.tunnel
  const t = s.tunnel
  if (t.status === 'on' || t.status === 'starting') {
    return (
      <div className="flex flex-wrap items-center gap-3">
        {t.status === 'starting' && <span className="text-xs text-zinc-500">{T.starting}</span>}
        <Button disabled={busy} onClick={() => void run(() => api.stopTunnel(s.id))}>
          {T.stop}
        </Button>
      </div>
    )
  }
  return (
    <div className="space-y-2 rounded-md border border-zinc-200 p-3 dark:border-zinc-700">
      {t.error && <ErrorText>{t.error}</ErrorText>}
      <p className="text-xs text-zinc-600 dark:text-zinc-400">{T.offHint}</p>
      <ConfirmButton
        variant="secondary"
        label={T.start}
        title={T.confirmTitle}
        body={T.confirmBody}
        onConfirm={() => api.startTunnel(s.id).then(() => run(async () => {}))}
      />
    </div>
  )
}

function useRemaining(s: LiveSession | undefined): string | null {
  const [now, setNow] = useState(() => Date.now())
  const running = s?.status === 'running' && !!s.ends_at
  useEffect(() => {
    if (!running) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [running])
  if (!s || !running || !s.ends_at) return null
  // Reloj del Mac (backend) frente al de la UI: error máximo, el intervalo de consulta.
  const offset = Date.parse(s.server_now) - now
  return formatRemaining(Math.max(0, Date.parse(s.ends_at) - (now + offset)))
}

export function LiveRoom({ id }: { id: string }) {
  const navigate = useNavigate()
  const q = useQuery(() => api.getLive(id), [id])
  const s = q.data
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [projecting, setProjecting] = useState(false)
  const { reload } = q
  const closed = s?.status === 'closed'
  const fast = !!s?.quiz && s.status === 'running'
  useEffect(() => {
    if (closed) return
    const t = window.setInterval(() => reload(), fast ? QUIZ_POLL_MS : POLL_MS)
    return () => window.clearInterval(t)
  }, [closed, fast, reload])
  const remaining = useRemaining(s)

  if (!s) {
    return (
      <div className="mx-auto max-w-5xl px-10 py-10">
        {q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}
      </div>
    )
  }

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const admitted = s.participants.filter((p) => p.status === 'admitted').length
  const open = s.status === 'lobby' || s.status === 'running'

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <button
        type="button"
        className="mb-3 text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: 'exam', id: s.exam_id })}
      >
        ← {es.live.back}
      </button>
      <PageHeader
        title={s.exam_title}
        subtitle={`${es.live.modeShort[s.mode]} · ${es.live.status[s.status]}${
          remaining ? ` · ${es.live.timeLeft(remaining)}` : ''
        }`}
        actions={
          <>
            {s.status === 'lobby' && (
              <Button
                variant="primary"
                disabled={busy || admitted === 0}
                title={admitted === 0 ? es.live.startNeedsPeople : es.live.startHint}
                onClick={() => void run(() => api.liveAction(s.id, 'start'))}
              >
                {s.quiz ? es.live.quiz.start : es.live.start}
              </Button>
            )}
            {s.quiz && !closed && (
              <Button onClick={() => setProjecting(true)}>{es.live.quiz.project}</Button>
            )}
            {s.quiz && s.status === 'running' && (
              <Button
                disabled={busy}
                title={es.live.quiz.nextHint}
                onClick={() => void run(() => api.quizNext(s.id))}
              >
                {es.live.quiz.next}
              </Button>
            )}
            {s.status === 'running' && (
              <ConfirmButton
                variant="danger"
                label={s.quiz ? es.live.quiz.finish : es.live.finish}
                title={s.quiz ? es.live.quiz.finish : es.live.finish}
                body={s.quiz ? es.live.quiz.finishConfirm : es.live.finishConfirm}
                onConfirm={() => api.liveAction(s.id, 'finish').then(reload)}
              />
            )}
            {s.mode === 'graded' && !s.published && (s.status === 'finished' || closed) && (
              <Button
                variant="primary"
                disabled={busy}
                title={es.live.publishHint}
                onClick={() => void run(() => api.liveAction(s.id, 'publish'))}
              >
                {es.live.publish}
              </Button>
            )}
            {!closed ? (
              <ConfirmButton
                label={es.live.close}
                title={es.live.close}
                body={es.live.closeConfirm}
                onConfirm={() => api.liveAction(s.id, 'close').then(reload)}
              />
            ) : (
              <ConfirmButton
                variant="danger"
                label={es.live.deleteData}
                title={es.live.deleteData}
                body={es.live.deleteConfirm}
                onConfirm={async () => {
                  await api.deleteLive(s.id)
                  navigate({ name: 'exam', id: s.exam_id })
                }}
              />
            )}
          </>
        }
      />
      <ErrorText>{error ?? q.error}</ErrorText>

      <div className="space-y-6">
        {s.network_problem && (
          <Card className="border-amber-300 text-sm dark:border-amber-800">
            {s.network_problem}
          </Card>
        )}
        {s.published && (
          <p className="text-sm text-emerald-700 dark:text-emerald-400">{es.live.published}</p>
        )}

        {s.url && s.qr && s.status !== 'finished' && (
          <Card className="grid gap-6 md:grid-cols-[auto_1fr]">
            <div className="flex flex-col items-center gap-2">
              <QrCode rows={s.qr} label={es.live.scan} />
              <span className="text-sm font-medium">{es.live.scan}</span>
            </div>
            <div className="min-w-0 space-y-3 text-sm">
              <p className="text-zinc-600 dark:text-zinc-400">
                {s.tunnel.status === 'on' ? es.live.tunnel.on : es.live.sameWifi}
              </p>
              <div>
                <p className="text-xs font-medium text-zinc-500">{es.live.link}</p>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 break-all rounded bg-zinc-100 px-2 py-1 text-base dark:bg-zinc-800">
                    {s.url}
                  </code>
                  <CopyButton text={() => s.url ?? ''} />
                </div>
              </div>
              <p>
                <span className="text-xs font-medium text-zinc-500">{es.live.code}: </span>
                <span className="font-mono text-lg tracking-widest">{s.code}</span>
              </p>
              {s.https_attempts > 0 && (
                <p className="rounded-md bg-amber-50 p-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                  {es.live.https(s.https_attempts)}
                </p>
              )}
              {s.tunnel.status !== 'on' && (
                <p className="text-xs text-zinc-500">{es.live.networkHelp}</p>
              )}
              {open && <TunnelControl session={s} busy={busy} run={run} />}
              {open && (
                <div className="flex items-center gap-3">
                  <Button
                    disabled={busy}
                    onClick={() => void run(() => api.lockLive(s.id, !s.locked))}
                  >
                    {s.locked ? es.live.unlock : es.live.lock}
                  </Button>
                  {s.locked && <span className="text-xs text-zinc-500">{es.live.locked}</span>}
                </div>
              )}
            </div>
          </Card>
        )}

        {s.quiz && <QuizPanel session={s} />}
        <AnswerKey liveId={s.id} />
        <Participants session={s} busy={busy} run={run} />
        {!s.quiz && (s.status === 'finished' || closed) && <Results session={s} />}
      </div>
      {projecting && s.quiz && (
        <QuizProjector
          session={s}
          busy={busy}
          onClose={() => setProjecting(false)}
          onNext={() => void run(() => api.quizNext(s.id))}
        />
      )}
    </div>
  )
}

function Participants({
  session: s,
  busy,
  run,
}: {
  session: LiveSession
  busy: boolean
  run: (fn: () => Promise<unknown>) => Promise<void>
}) {
  const live = s.status !== 'closed'
  const points = new Map(s.quiz?.leaderboard.map((r) => [r.participant_id, r.score]) ?? [])
  return (
    <Card>
      <h2 className="mb-3 font-medium">
        {es.live.participants} ({s.participants.length})
      </h2>
      {s.participants.length === 0 ? (
        <p className="text-sm text-zinc-500">{es.live.noParticipants}</p>
      ) : (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {s.participants.map((p: LiveParticipant) => {
            const g = grade10(p.score, p.max_score)
            return (
              <li key={p.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                {live && (
                  <span
                    className={`size-2 rounded-full ${p.online ? 'bg-emerald-500' : 'bg-zinc-300 dark:bg-zinc-600'}`}
                    title={p.online ? es.live.online : es.live.offline}
                    aria-label={p.online ? es.live.online : es.live.offline}
                  />
                )}
                <span className="min-w-40 flex-1">
                  <span className="font-medium">{p.name}</span>
                  {p.device && <span className="ml-2 text-xs text-zinc-500">{p.device}</span>}
                  {p.left_count > 0 && (
                    <span className="ml-2 text-xs text-amber-700 dark:text-amber-400">
                      {es.live.left(p.left_count)}
                    </span>
                  )}
                </span>
                {s.quiz ? (
                  <span className="text-xs text-zinc-500 tabular-nums">
                    {es.live.quiz.points(points.get(p.id) ?? 0)}
                  </span>
                ) : (
                  <span className="text-xs text-zinc-500">{participantState(p)}</span>
                )}
                {p.attempt_status === 'graded' && g != null && (
                  <span className="font-medium tabular-nums">{g.toLocaleString('es-ES')}/10</span>
                )}
                {p.status === 'pending' && live && (
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() => void run(() => api.liveParticipant(s.id, p.id, 'admit'))}
                  >
                    {es.live.admit}
                  </Button>
                )}
                {live && s.status !== 'finished' && (
                  <ConfirmButton
                    label={es.live.kick}
                    title={es.live.kick}
                    body={es.live.kickConfirm(p.name)}
                    onConfirm={() => api.liveParticipant(s.id, p.id, 'kick')}
                  />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function answerText(q: LiveQuestionStat, value: unknown): string {
  if (value == null || value === '') return es.live.blank
  if (q.type === 'single' && typeof value === 'number') return q.options[value] ?? es.live.blank
  if (q.type === 'true_false') return value ? es.exams.trueLabel : es.exams.falseLabel
  return String(value)
}

/** Clave de respuestas con su fuente: solo en la app del profesor (cerrada por defecto, por si
 * proyecta la pantalla con el QR). Se carga al abrirla. */
function AnswerKey({ liveId }: { liveId: string }) {
  const [shown, setShown] = useState(false)
  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="flex-1 font-medium">{es.live.answerKey}</h2>
        <Button aria-expanded={shown} onClick={() => setShown(!shown)}>
          {shown ? es.live.hideKey : es.live.showKey}
        </Button>
      </div>
      <p className="text-xs text-zinc-500">{es.live.answerKeyHint}</p>
      {shown && <AnswerKeyList liveId={liveId} />}
    </Card>
  )
}

function AnswerKeyList({ liveId }: { liveId: string }) {
  const q = useQuery(() => api.liveResults(liveId), [liveId])
  if (!q.data) return q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />
  const qs = [...q.data.questions].sort((a, b) => a.position - b.position)
  return (
    <ol className="space-y-5">
      {qs.map((x, i) => (
        <li key={x.question_id} className="space-y-2 text-sm">
          <p className="font-medium">
            {i + 1}. {x.stem}
          </p>
          {x.type === 'single' ? (
            <ul className="space-y-1">
              {x.options.map((o, j) => (
                <li
                  key={j}
                  className={
                    j === x.answer
                      ? 'rounded bg-emerald-50 px-2 py-1 font-medium text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200'
                      : 'px-2 py-1 text-zinc-600 dark:text-zinc-400'
                  }
                >
                  {j === x.answer ? '✓ ' : ''}
                  {o}
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded bg-emerald-50 px-2 py-1 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
              <span className="font-medium">{es.exams.correctAnswer}: </span>
              {answerText(x, x.answer)}
            </p>
          )}
          {x.rubric.length > 0 && (
            <div>
              <span className="text-zinc-500">{es.exams.rubric}:</span>
              <ul className="ml-5 list-disc">
                {x.rubric.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {x.justification && (
            <p>
              <span className="text-zinc-500">{es.exams.why}: </span>
              {x.justification}
            </p>
          )}
          <div className="space-y-2">
            <div className="text-xs text-zinc-500">{es.exams.evidence}</div>
            {x.evidence.length ? (
              x.evidence.map((c) => <CitationPanel key={c.ref} ref_={c.ref} cite={c} />)
            ) : (
              <p className="text-xs text-zinc-500">{es.live.noEvidence}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

function Results({ session: s }: { session: LiveSession }) {
  const q = useQuery(() => api.liveResults(s.id), [s.id])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [openRow, setOpenRow] = useState<string | null>(null)
  const { reload } = q
  const grading = q.data?.participants.some((p) => p.attempt_status === 'grading') ?? false
  useEffect(() => {
    if (!grading) return
    const t = window.setInterval(() => reload(), POLL_MS)
    return () => window.clearInterval(t)
  }, [grading, reload])
  const r = q.data
  if (!r) return <Card>{q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}</Card>

  const qs = [...r.questions].sort((a, b) => a.position - b.position)
  const avg = classAverage(r)
  const exportCsv = async () => {
    setError(null)
    setNotice(null)
    try {
      const path = native ? await native.saveText(`${s.exam_title}.csv`, resultsCsv(r)) : null
      if (path) setNotice(es.live.exported(path))
    } catch (e) {
      setError(e instanceof Error || typeof e === 'string' ? nativeError(e) : errorMessage(e))
    }
  }
  const adjust = async (row: LiveResultRow, questionId: string, points: number) => {
    setError(null)
    try {
      await api.adjustLive(s.id, row.id, questionId, points)
      reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex-1 font-medium">{es.live.results}</h2>
        {avg != null && (
          <span className="text-sm text-zinc-500">
            {es.live.average(avg.toLocaleString('es-ES'))}
          </span>
        )}
        <Button onClick={() => void exportCsv()} disabled={!native}>
          {es.live.exportCsv}
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>
      {notice && <p className="text-sm text-zinc-500">{notice}</p>}

      <div>
        <h3 className="mb-2 text-sm font-medium">{es.live.byQuestion}</h3>
        <ol className="space-y-1 text-sm">
          {qs.map((x, i) => (
            <li key={x.question_id} className="flex gap-3">
              <span className="w-8 shrink-0 text-zinc-500">{i + 1}.</span>
              <span className="min-w-0 flex-1 truncate" title={x.stem}>
                {x.stem}
              </span>
              <span className="shrink-0 tabular-nums text-zinc-600 dark:text-zinc-400">
                {x.ratio == null ? es.live.noAnswers : es.live.ratio(Math.round(x.ratio * 100))}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {r.participants.map((row) => {
          const g = grade10(row.score, row.max_score)
          const expanded = openRow === row.id
          const byQ = new Map(row.answers.map((a) => [a.question_id, a]))
          return (
            <li key={row.id} className="py-2 text-sm">
              <button
                type="button"
                className="flex w-full items-center gap-3 text-left"
                aria-expanded={expanded}
                onClick={() => setOpenRow(expanded ? null : row.id)}
              >
                <span className="flex-1 font-medium">{row.name}</span>
                <span className="text-xs text-zinc-500">{participantState(row)}</span>
                <span className="w-16 text-right font-medium tabular-nums">
                  {g == null ? '—' : `${g.toLocaleString('es-ES')}/10`}
                </span>
              </button>
              {expanded && (
                <ol className="mt-2 space-y-3 border-l-2 border-zinc-200 pl-4 dark:border-zinc-700">
                  {qs.map((x, i) => {
                    const a = byQ.get(x.question_id)
                    return (
                      <li key={x.question_id} className="space-y-1">
                        <p className="text-zinc-500">
                          {i + 1}. {x.stem}
                        </p>
                        <p>{answerText(x, a?.answer)}</p>
                        {a?.feedback && (
                          <p className="text-xs text-zinc-500">
                            {es.live.aiGraded}: {a.feedback}
                          </p>
                        )}
                        <div className="flex items-center gap-2 text-xs">
                          <span className="tabular-nums">
                            {a?.points == null ? '—' : a.points.toLocaleString('es-ES')} p
                          </span>
                          {a?.adjusted && <span className="text-zinc-500">{es.live.adjusted}</span>}
                          {row.attempt_status === 'graded' && (
                            <label className="ml-auto flex items-center gap-1">
                              <span className="text-zinc-500">{es.live.adjust}</span>
                              <select
                                className="rounded border border-zinc-300 bg-white px-1 dark:border-zinc-700 dark:bg-zinc-900"
                                value={
                                  a?.points != null && [0, 0.5, 1].includes(a.points)
                                    ? String(a.points)
                                    : ''
                                }
                                onChange={(e) =>
                                  void adjust(row, x.question_id, Number(e.target.value))
                                }
                              >
                                <option value="" disabled>
                                  —
                                </option>
                                <option value="0">0</option>
                                <option value="0.5">0,5</option>
                                <option value="1">1</option>
                              </select>
                            </label>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
