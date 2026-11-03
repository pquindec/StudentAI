import { useEffect, useState } from 'react'
import { es } from '../i18n/es'
import { api, type Job } from '../lib/api'
import { useNavigate } from '../lib/nav'

/** Trabajos en segundo plano: consulta con más frecuencia mientras hay alguno activo. */
export function JobsPanel({ enabled }: { enabled: boolean }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [cancelling, setCancelling] = useState<Set<string>>(new Set())
  const navigate = useNavigate()

  useEffect(() => {
    if (!enabled) return
    const ac = new AbortController()
    const tick = async () => {
      let delay = 4000
      try {
        const list = await api.listJobs(true)
        if (ac.signal.aborted) return
        setJobs(list)
        if (list.length) delay = 1000
      } catch {
        // El estado del servicio ya se muestra aparte; reintenta en el siguiente ciclo.
      }
      if (ac.signal.aborted) return
      const timer = window.setTimeout(() => void tick(), delay)
      ac.signal.addEventListener('abort', () => window.clearTimeout(timer), { once: true })
    }
    void tick()
    return () => ac.abort()
  }, [enabled])

  if (!jobs.length) return null

  const cancel = async (id: string) => {
    setCancelling((s) => new Set(s).add(id))
    try {
      await api.cancelJob(id)
    } catch {
      setCancelling((s) => {
        const n = new Set(s)
        n.delete(id)
        return n
      })
    }
  }

  return (
    <section
      aria-label={es.jobs.title}
      className="border-t border-zinc-200 px-3 py-3 dark:border-zinc-800"
    >
      <h2 className="px-2 pb-2 text-xs font-medium tracking-wide text-zinc-500 uppercase">
        {es.jobs.title}
      </h2>
      <ul className="space-y-2">
        {jobs.map((j) => (
          <li
            key={j.id}
            className="rounded-md bg-white px-2 py-2 text-xs shadow-sm dark:bg-zinc-800"
          >
            <button
              type="button"
              className="block w-full truncate text-left font-medium hover:underline"
              onClick={() => j.source_id && navigate({ name: 'source', id: j.source_id })}
            >
              {j.source_title ?? es.jobs.type[j.type] ?? j.type}
            </button>
            <div className="mt-0.5 text-zinc-500">
              {j.status === 'queued' ? es.jobs.queued : (j.message ?? es.jobs.type[j.type] ?? '')}
            </div>
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(j.progress * 100)}
              className="mt-1.5 h-1 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-700"
            >
              <div
                className="h-full bg-accent-500 transition-all"
                style={{ width: `${j.progress * 100}%` }}
              />
            </div>
            <button
              type="button"
              disabled={cancelling.has(j.id)}
              onClick={() => void cancel(j.id)}
              className="mt-1 text-zinc-500 hover:text-red-600 disabled:opacity-60"
            >
              {cancelling.has(j.id) ? es.jobs.cancelling : es.jobs.cancel}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
