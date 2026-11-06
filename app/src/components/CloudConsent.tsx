import { createContext, type ReactNode, useCallback, useContext, useRef, useState } from 'react'
import { es } from '../i18n/es'
import { api, type CloudAsk, type CloudPreview } from '../lib/api'
import { errorMessage } from '../lib/useQuery'
import { Button, ErrorText, Modal } from './ui'

/**
 * Consentimiento antes de enviar algo a Claude (Fase 8).
 *
 * `askCloud(petición)` devuelve:
 * - el id del consentimiento si el usuario aprueba el envío (o ya lo aprobó para la sesión);
 * - `null` si va en local (Claude desactivado, tarea local, sin vía, límite… o «Hacerlo en local»);
 * - `false` si el usuario cancela (no se crea nada).
 */
type Ask = (body: CloudAsk) => Promise<string | null | false>

const CloudContext = createContext<Ask>(() => Promise.resolve(null))

export const useCloudConsent = () => useContext(CloudContext)

interface Pending {
  body: CloudAsk
  preview: CloudPreview
  resolve: (v: string | null | false) => void
}

export function CloudConsentProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null)
  const pendingRef = useRef<Pending | null>(null)

  const ask = useCallback<Ask>(async (body) => {
    const preview = await api.cloudPreview(body)
    if (!preview.cloud) return null
    if (preview.session_consent_id) return preview.session_consent_id
    return new Promise((resolve) => {
      const p = { body, preview, resolve }
      pendingRef.current = p
      setPending(p)
    })
  }, [])

  const finish = (v: string | null | false) => {
    pendingRef.current?.resolve(v)
    pendingRef.current = null
    setPending(null)
  }

  return (
    <CloudContext.Provider value={ask}>
      {children}
      {pending && <ConsentDialog key={pending.preview.text.length} p={pending} onDone={finish} />}
    </CloudContext.Provider>
  )
}

function ConsentDialog({ p, onDone }: { p: Pending; onDone: (v: string | null | false) => void }) {
  const { preview: v, body } = p
  const [session, setSession] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const kind = es.cloud.kind[body.kind]
  const via = v.via ? es.cloud.viaShort[v.via] : ''

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      const c = await api.giveCloudConsent({ ...body, mode: session ? 'session' : 'once' })
      onDone(c.id)
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <Modal open wide title={es.cloud.consentTitle} onClose={() => onDone(false)}>
      <div className="space-y-3 text-sm">
        <p>
          {es.cloud.consentWhat(kind, v.tasks.map((t) => es.cloud.taskVerb[t]).join(' y '))}
          <br />
          <span className="text-zinc-600 dark:text-zinc-400">
            {es.cloud.consentModel(via, v.model)}
          </span>
        </p>
        {v.sources.length > 0 && (
          <div>
            <p className="font-medium">{es.cloud.consentSources}</p>
            <ul className="list-disc pl-5 text-zinc-700 dark:text-zinc-300">
              {v.sources.map((s) => (
                <li key={s.id}>{s.title}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-zinc-700 dark:text-zinc-300">
          {es.cloud.consentAmount(v.fragments, v.chars)}
        </p>
        {v.notes.map((n) =>
          es.cloud.notes[n] ? (
            <p key={n} className="rounded-md bg-zinc-100 px-2 py-1 text-xs dark:bg-zinc-800">
              {es.cloud.notes[n]}
            </p>
          ) : null,
        )}
        <div>
          <p className="font-medium">{es.cloud.consentCost(v.est_cost_usd)}</p>
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            {es.cloud.consentMonth(v.spent_usd, v.limit_usd)}
            {v.via === 'plan' ? ` · ${es.cloud.consentPlanCost}` : ''}
          </p>
        </div>
        <details className="rounded-md border border-zinc-200 dark:border-zinc-800">
          <summary className="cursor-pointer px-3 py-2 font-medium">{es.cloud.consentText}</summary>
          <pre className="max-h-64 overflow-auto px-3 pb-3 text-xs whitespace-pre-wrap">
            {v.text}
          </pre>
          {v.truncated && (
            <p className="px-3 pb-2 text-xs text-zinc-500">{es.cloud.consentTruncated}</p>
          )}
        </details>
        <p className="text-xs text-zinc-500">{es.cloud.consentInstructions}</p>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={session} onChange={(e) => setSession(e.target.checked)} />
          {es.cloud.consentSession(kind)}
        </label>
        {error && <ErrorText>{error}</ErrorText>}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" disabled={busy} onClick={() => onDone(false)}>
            {es.common.cancel}
          </Button>
          <Button disabled={busy} onClick={() => onDone(null)}>
            {es.cloud.consentLocal}
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => void send()}>
            {es.cloud.consentSend}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
