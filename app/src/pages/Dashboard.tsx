import { useCallback, useEffect, useState } from 'react'
import { StatusDot } from '../components/StatusDot'
import { es } from '../i18n/es'
import { api, ApiError, type SystemInfo } from '../lib/api'
import type { BackendStatus } from '../lib/backendStatus'
import { useNavigate } from '../lib/nav'
import { useQuery } from '../lib/useQuery'

/** Tarjetas pendientes de hoy (de todas las asignaturas) y racha. */
function TodayCard() {
  const navigate = useNavigate()
  const study = useQuery(() => api.study({}), [])
  const stats = useQuery(() => api.stats({ days: 7 }), [])
  const s = study.data
  if (!s) return null
  const pending = s.learning + s.review + s.new
  const streak = stats.data?.streak ?? 0
  return (
    <section className="mt-8 flex flex-wrap items-center gap-4 rounded-xl border border-zinc-200 p-5 dark:border-zinc-800">
      <div className="flex-1">
        <h2 className="text-sm font-medium">{es.home.dueTitle}</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          {es.home.dueBody(pending)}
          {streak ? ` · ${es.home.streak(streak)}` : ''}
        </p>
      </div>
      <button
        type="button"
        className="text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: 'stats' })}
      >
        {es.home.goStats}
      </button>
      {pending > 0 && (
        <button
          type="button"
          className="rounded-md bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700"
          onClick={() => navigate({ name: 'review', back: { name: 'dashboard' } })}
        >
          {es.home.study}
        </button>
      )}
    </section>
  )
}

export function Dashboard({ status }: { status: BackendStatus }) {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchInfo = useCallback(
    () =>
      api
        .systemInfo()
        .then((i) => {
          setInfo(i)
          setError(null)
        })
        .catch((e: unknown) => setError(e instanceof ApiError ? e.message : es.backend.failed)),
    [],
  )

  useEffect(() => {
    if (status.state === 'ready') void fetchInfo()
  }, [status.state, fetchInfo])

  const retry = () => {
    setError(null)
    void fetchInfo()
  }

  return (
    <div className="mx-auto max-w-4xl px-10 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{es.dashboard.title}</h1>
      <p className="mt-1 text-sm text-zinc-500">{es.dashboard.subtitle}</p>

      {status.state === 'ready' && <TodayCard />}

      <section
        aria-labelledby="system-title"
        className="mt-8 rounded-xl border border-zinc-200 p-5 dark:border-zinc-800"
      >
        <div className="flex items-center gap-2">
          <StatusDot status={status} />
          <h2 id="system-title" className="text-sm font-medium">
            {es.dashboard.systemTitle} — {es.backend[status.state]}
          </h2>
        </div>

        {status.state === 'failed' && (
          <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
            {status.message}
          </p>
        )}

        {error && (
          <div role="alert" className="mt-3 flex items-center gap-3 text-sm text-red-600">
            <span>{error}</span>
            <button
              type="button"
              onClick={retry}
              className="rounded-md border border-red-300 px-2 py-0.5 hover:bg-red-50 dark:hover:bg-red-950"
            >
              {es.dashboard.retry}
            </button>
          </div>
        )}

        {info && (
          <dl
            data-testid="system-info"
            className="selectable mt-4 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm"
          >
            <dt className="text-zinc-500">{es.dashboard.version}</dt>
            <dd>{info.version}</dd>
            <dt className="text-zinc-500">{es.dashboard.database}</dt>
            <dd>
              SQLite {info.sqlite_version} · {es.dashboard.schema(info.schema_version)}
            </dd>
            <dt className="text-zinc-500">{es.dashboard.search}</dt>
            <dd>{info.fts5_available ? es.dashboard.available : es.dashboard.unavailable}</dd>
            <dt className="text-zinc-500">{es.dashboard.dataDir}</dt>
            <dd className="font-mono text-xs break-all">{info.data_dir}</dd>
          </dl>
        )}
        <p className="mt-4 text-xs text-zinc-500">{es.dashboard.privacy}</p>
      </section>
    </div>
  )
}
