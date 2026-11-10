import { useState } from 'react'
import { es } from '../i18n/es'
import { api, ApiError, type LiveIn } from '../lib/api'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Button, Card, ErrorText, Field, inputClass, Modal } from './ui'

/** Botón «Compartir en vivo» de un examen listo: elige el tipo de sesión y abre la sala. */
export function LiveShareButton({
  examId,
  timeLimit,
}: {
  examId: string
  timeLimit: number | null
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<LiveIn['mode']>('practice')
  const [minutes, setMinutes] = useState<string>(timeLimit ? String(timeLimit) : '')
  const [showResults, setShowResults] = useState(true)
  const [seconds, setSeconds] = useState(20)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  const n = Number(minutes)
  const validTime = minutes === '' || (Number.isInteger(n) && n >= 1 && n <= 240)

  const create = async () => {
    setBusy(true)
    setError(null)
    setOpenId(null)
    try {
      const s = await api.createLive(examId, {
        mode,
        time_limit_min: minutes === '' || mode === 'quiz' ? null : n,
        show_results: mode === 'practice' ? showResults : false,
        question_s: seconds,
      })
      navigate({ name: 'live', id: s.id })
    } catch (e) {
      setError(errorMessage(e))
      if (e instanceof ApiError && e.code === 'live_open') {
        const other = (await api.listLive()).find((x) => x.status !== 'closed')
        if (other) setOpenId(other.id)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>{es.live.share}</Button>
      <Modal open={open} title={es.live.shareTitle} onClose={() => setOpen(false)}>
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{es.live.shareHint}</p>
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
              {es.live.mode}
            </legend>
            {(['practice', 'graded', 'quiz'] as const).map((m) => (
              <label key={m} className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="live-mode"
                  className="mt-1"
                  checked={mode === m}
                  onChange={() => setMode(m)}
                />
                <span>{es.live.modes[m]}</span>
              </label>
            ))}
          </fieldset>
          {mode === 'quiz' ? (
            <Field label={es.live.questionS} hint={es.live.quizHint}>
              <select
                className={inputClass}
                value={seconds}
                onChange={(e) => setSeconds(Number(e.target.value))}
              >
                {[10, 15, 20, 30, 45, 60].map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label={es.live.timeLimit} hint={es.live.noLimit}>
              <input
                type="number"
                min={1}
                max={240}
                className={inputClass}
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
              />
            </Field>
          )}
          {mode === 'practice' && (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={showResults}
                onChange={(e) => setShowResults(e.target.checked)}
              />
              <span>{es.live.showResults}</span>
            </label>
          )}
          <p className="text-xs text-zinc-500">{es.live.privacy}</p>
          <ErrorText>{error}</ErrorText>
          <div className="flex justify-end gap-2">
            <Button onClick={() => setOpen(false)}>{es.common.cancel}</Button>
            {openId ? (
              <Button variant="primary" onClick={() => navigate({ name: 'live', id: openId })}>
                {es.live.openSession}
              </Button>
            ) : (
              <Button
                variant="primary"
                disabled={busy || (mode !== 'quiz' && !validTime)}
                onClick={() => void create()}
              >
                {es.live.open}
              </Button>
            )}
          </div>
        </div>
      </Modal>
    </>
  )
}

/** Sesiones en vivo anteriores de un examen. */
export function LiveSessions({ examId }: { examId: string }) {
  const navigate = useNavigate()
  const q = useQuery(() => api.listLive(examId), [examId])
  const list = q.data ?? []
  return (
    <Card>
      <h2 className="mb-3 font-medium">{es.live.sessions}</h2>
      <ErrorText>{q.error}</ErrorText>
      {list.length === 0 ? (
        <p className="text-sm text-zinc-500">{es.live.noSessions}</p>
      ) : (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {list.map((s) => (
            <li key={s.id} className="flex items-center gap-3 py-2 text-sm">
              <span className="flex-1">
                {formatDate(s.created_at)} · {es.live.modeShort[s.mode]} ·{' '}
                {es.live.admittedN(s.admitted)}
              </span>
              <span className="text-xs text-zinc-500">{es.live.status[s.status]}</span>
              <Button onClick={() => navigate({ name: 'live', id: s.id })}>{es.live.view}</Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
