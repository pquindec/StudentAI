import { useState } from 'react'
import { es } from '../i18n/es'
import { api, type AiStatus, type KeepAlive } from '../lib/api'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Card, ErrorText, Field, inputClass, Loading } from './ui'

const gb = (mb: number) => (mb / 1024).toFixed(1).replace('.', ',')

/** Estado de Ollama, modelo elegido y memoria (AI Resource Manager). */
export function AiPanel() {
  const q = useQuery(() => api.aiStatus(), [])
  const [error, setError] = useState<string | null>(null)
  const s = q.data

  const act = async (fn: () => Promise<AiStatus>) => {
    setError(null)
    try {
      await fn()
      q.reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  if (!s) return <Card>{q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}</Card>
  const chosen = s.models.find((m) => m.name === s.model)

  return (
    <Card className="space-y-3">
      <h2 className="font-medium">{es.ai.title}</h2>
      <p
        className={`text-sm ${s.running ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-700 dark:text-amber-400'}`}
      >
        {s.running ? es.ai.running(s.version ?? '') : es.ai.notRunning}
      </p>
      {s.running && (
        <>
          <div className="flex flex-wrap gap-4">
            <Field label={es.ai.model}>
              <select
                className={`${inputClass} w-auto`}
                value={s.model}
                onChange={(e) => void act(() => api.updateAiSettings({ model: e.target.value }))}
              >
                {s.models.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name} {m.installed ? '' : '—'}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={es.ai.keepAlive}>
              <select
                className={`${inputClass} w-auto`}
                value={s.keep_alive}
                onChange={(e) =>
                  void act(() => api.updateAiSettings({ keep_alive: e.target.value as KeepAlive }))
                }
              >
                {(Object.keys(es.ai.keepAliveOptions) as KeepAlive[]).map((k) => (
                  <option key={k} value={k}>
                    {es.ai.keepAliveOptions[k]}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <ul className="space-y-1 text-xs text-zinc-500">
            {chosen && !chosen.installed && (
              <li className="text-amber-700 dark:text-amber-400">{es.ai.missing(chosen.name)}</li>
            )}
            {s.light_model && <li>{es.ai.light(s.light_model)}</li>}
            {s.available_mb != null && <li>{es.ai.memory(gb(s.available_mb))}</li>}
            {s.loaded.map((m) => (
              <li key={m.name}>{es.ai.loaded(m.name, gb(m.size_mb))}</li>
            ))}
          </ul>
        </>
      )}
      <ErrorText>{error}</ErrorText>
    </Card>
  )
}
