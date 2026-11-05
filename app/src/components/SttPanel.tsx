import { useEffect, useState } from 'react'
import { es } from '../i18n/es'
import { type AudioKeepDays, api, type SttLanguage, type SttStatus } from '../lib/api'
import { formatBytes } from '../lib/format'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Button, Card, ErrorText, Field, inputClass, Loading } from './ui'

/** Modelos de transcripción (descarga explícita) y preferencias de idioma. */
export function SttPanel() {
  const q = useQuery(() => api.sttStatus(), [])
  const [error, setError] = useState<string | null>(null)
  const s = q.data
  const downloading = s?.models.some((m) => m.download_job_id)

  const { reload } = q
  useEffect(() => {
    if (!downloading) return
    const t = window.setInterval(() => reload(), 1000)
    return () => window.clearInterval(t)
  }, [downloading, reload])

  const act = async (fn: () => Promise<SttStatus>) => {
    setError(null)
    try {
      await fn()
      reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  if (!s) return <Card>{q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}</Card>
  const vad = s.models.find((m) => m.kind === 'vad')

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="font-medium">{es.stt.title}</h2>
        <p
          className={`mt-1 text-sm ${s.ready ? 'text-emerald-700 dark:text-emerald-400' : 'text-zinc-500'}`}
        >
          {!s.whisper_available ? es.stt.whisperMissing : s.ready ? es.stt.ready : es.stt.notReady}
        </p>
      </div>
      <ul className="space-y-3">
        {s.models
          .filter((m) => m.kind === 'stt')
          .map((m) => {
            const extra = vad && !vad.installed ? vad.size_bytes : 0
            return (
              <li key={m.id} className="flex flex-wrap items-center gap-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{m.label}</div>
                  <div className="text-xs text-zinc-500">{m.description}</div>
                </div>
                {m.download_job_id ? (
                  <span className="text-xs text-zinc-500">
                    {es.stt.downloading} {Math.round((m.download_progress ?? 0) * 100)} %
                  </span>
                ) : m.installed ? (
                  s.model === m.id ? (
                    <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">
                      {es.stt.inUse}
                    </span>
                  ) : (
                    <Button onClick={() => void act(() => api.updateSttSettings({ model: m.id }))}>
                      {es.stt.use}
                    </Button>
                  )
                ) : (
                  <Button
                    variant={m.id === s.model ? 'primary' : 'secondary'}
                    onClick={() =>
                      void act(async () => {
                        await api.updateSttSettings({ model: m.id })
                        return api.downloadModel(m.id)
                      })
                    }
                  >
                    {es.stt.download(formatBytes(m.size_bytes + extra))}
                  </Button>
                )}
              </li>
            )
          })}
      </ul>
      <Field label={es.stt.language}>
        <select
          className={`${inputClass} w-auto`}
          value={s.language}
          onChange={(e) =>
            void act(() => api.updateSttSettings({ language: e.target.value as SttLanguage }))
          }
        >
          {(Object.keys(es.stt.languages) as SttLanguage[]).map((l) => (
            <option key={l} value={l}>
              {es.stt.languages[l]}
            </option>
          ))}
        </select>
      </Field>
      <Field label={es.stt.keepAudio}>
        <select
          className={`${inputClass} w-auto`}
          value={s.audio_keep_days}
          onChange={(e) =>
            void act(() =>
              api.updateSttSettings({ audio_keep_days: Number(e.target.value) as AudioKeepDays }),
            )
          }
        >
          {([7, 30, 0] as AudioKeepDays[]).map((d) => (
            <option key={d} value={d}>
              {es.stt.keepDays[d]}
            </option>
          ))}
        </select>
      </Field>
      <p className="text-xs text-zinc-500">{es.stt.keepAudioHint}</p>
      <p className="text-xs text-zinc-500">{es.stt.privacy}</p>
      <ErrorText>{error}</ErrorText>
    </Card>
  )
}
