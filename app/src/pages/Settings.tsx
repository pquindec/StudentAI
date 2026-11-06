import { useState } from 'react'
import { es, usd } from '../i18n/es'
import { api, type CloudSettingsIn, type CloudStatus, type CloudTask } from '../lib/api'
import { formatDate } from '../lib/format'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Button, Card, ErrorText, Field, inputClass, Loading, PageHeader } from '../components/ui'

const TASKS: CloudTask[] = ['chat', 'docs', 'generate', 'review']

export function Settings() {
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-10 py-10">
      <PageHeader title={es.cloud.title} subtitle={es.cloud.subtitle} />
      <CloudPanel />
    </div>
  )
}

function CloudPanel() {
  const q = useQuery(() => api.cloudStatus(), [])
  const audit = useQuery(() => api.cloudRequests(30), [])
  const [status, setStatus] = useState<CloudStatus | null>(null)
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const s = status ?? q.data

  const act = async (fn: () => Promise<CloudStatus | void>) => {
    setError(null)
    try {
      const out = await fn()
      if (out) setStatus(out)
      else setStatus(await api.cloudStatus())
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  const put = (body: CloudSettingsIn) => act(() => api.updateCloudSettings(body))

  if (!s) return <Card>{q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}</Card>

  return (
    <>
      <Card className="space-y-5">
        <h2 className="font-medium">{es.cloud.section}</h2>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={s.enabled}
            onChange={(e) => void put({ enabled: e.target.checked })}
          />
          <span>
            <span className="font-medium">{es.cloud.enabled}</span>
            <br />
            <span className="text-zinc-500">{es.cloud.enabledHint}</span>
          </span>
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={es.cloud.via}>
            <select
              className={inputClass}
              value={s.via_pref}
              onChange={(e) => void put({ via: e.target.value as CloudSettingsIn['via'] })}
            >
              {(['auto', 'api', 'plan'] as const).map((v) => (
                <option key={v} value={v}>
                  {es.cloud.vias[v]}
                </option>
              ))}
            </select>
          </Field>
          <Field label={es.cloud.model}>
            <select
              className={inputClass}
              value={s.model}
              onChange={(e) => void put({ model: e.target.value as CloudSettingsIn['model'] })}
            >
              {s.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {es.cloud.modelPrice(m.label, m.input_usd, m.output_usd)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {s.enabled && !s.via && (
          <p className="text-sm text-amber-700 dark:text-amber-400">{es.cloud.viaNone}</p>
        )}

        <div className="space-y-2">
          <h3 className="text-sm font-medium">{es.cloud.apiKey}</h3>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {s.api_key ? es.cloud.apiKeySaved(s.api_key) : es.cloud.apiKeyNone}
          </p>
          <div className="flex gap-2">
            <input
              type="password"
              autoComplete="off"
              className={inputClass}
              placeholder={es.cloud.apiKeyPlaceholder}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <Button
              disabled={!key.trim()}
              onClick={() =>
                void act(async () => {
                  const out = await api.setCloudApiKey(key.trim())
                  setKey('')
                  return out
                })
              }
            >
              {es.cloud.apiKeySave}
            </Button>
            {s.api_key && (
              <Button variant="ghost" onClick={() => void act(() => api.deleteCloudApiKey())}>
                {es.cloud.apiKeyDelete}
              </Button>
            )}
          </div>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">{es.cloud.plan}</h3>
          <div className="flex items-center gap-3">
            <p className="flex-1 text-sm text-zinc-600 dark:text-zinc-400">
              {!s.plan.installed
                ? es.cloud.planMissing
                : s.plan.logged_in
                  ? es.cloud.planOk(s.plan.plan)
                  : es.cloud.planNoLogin}
            </p>
            <Button variant="ghost" onClick={() => void act(() => api.cloudStatus(true))}>
              {es.cloud.planCheck}
            </Button>
          </div>
        </div>

        <fieldset className="space-y-1">
          <legend className="mb-1 text-sm font-medium">{es.cloud.tasks}</legend>
          {TASKS.map((t) => (
            <label key={t} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={s.tasks[t]}
                onChange={(e) => void put({ tasks: { [t]: e.target.checked } })}
              />
              {es.cloud.task[t]}
            </label>
          ))}
        </fieldset>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">{es.cloud.limits}</h3>
          <p className="text-xs text-zinc-500">{es.cloud.limitHint}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {(['api', 'plan'] as const).map((v) => (
              <Field key={v} label={es.cloud.vias[v]}>
                <input
                  type="number"
                  min={0}
                  max={1000}
                  step={0.5}
                  className={inputClass}
                  defaultValue={s.limits[v]}
                  onBlur={(e) => {
                    const n = Number(e.target.value)
                    if (Number.isFinite(n) && n !== s.limits[v])
                      void put(v === 'api' ? { limit_api: n } : { limit_plan: n })
                  }}
                />
                <span className="mt-1 block text-xs text-zinc-500">
                  {es.cloud.spent(s.spent[v], s.limits[v])}
                </span>
              </Field>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">{es.cloud.session}</h3>
          {s.session_consents.length === 0 ? (
            <p className="text-sm text-zinc-500">{es.cloud.sessionNone}</p>
          ) : (
            <div className="flex items-center gap-3">
              <ul className="flex-1 text-sm">
                {s.session_consents.map((c) => (
                  <li key={c.id}>
                    {es.cloud.kind[c.kind]} · {es.cloud.viaShort[c.via]} · {c.model}
                  </li>
                ))}
              </ul>
              <Button variant="ghost" onClick={() => void act(() => api.revokeSessionConsents())}>
                {es.cloud.sessionRevoke}
              </Button>
            </div>
          )}
        </div>
        <ErrorText>{error}</ErrorText>
      </Card>

      <Card className="space-y-3">
        <h2 className="font-medium">{es.cloud.audit}</h2>
        {!audit.data ? (
          <Loading />
        ) : audit.data.length === 0 ? (
          <p className="text-sm text-zinc-500">{es.cloud.auditNone}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-zinc-500">
                <tr>
                  {es.cloud.auditCols.map((c) => (
                    <th key={c} className="py-1 pr-3 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {audit.data.map((r) => (
                  <tr key={r.id} className="border-t border-zinc-200 dark:border-zinc-800">
                    <td className="py-1 pr-3">{formatDate(r.created_at)}</td>
                    <td className="py-1 pr-3">{r.task}</td>
                    <td className="py-1 pr-3">{es.cloud.viaShort[r.via]}</td>
                    <td className="py-1 pr-3">{r.model}</td>
                    <td className="py-1 pr-3">{es.cloud.status[r.status]}</td>
                    <td className="py-1 pr-3 tabular-nums">
                      {r.chars_sent.toLocaleString('es-ES')}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">{usd(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
