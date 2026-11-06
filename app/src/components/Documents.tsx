import { useCloudConsent } from './CloudConsent'
import { useState } from 'react'
import { es } from '../i18n/es'
import { api, type DocDetail, type DocKind, type GeneratedDoc } from '../lib/api'
import { isBusy } from '../lib/documents'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Button, ErrorText, Field, inputClass, Loading, Modal } from './ui'

const STATUS_STYLE: Record<GeneratedDoc['status'], string> = {
  queued: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  running: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  ready: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  cancelled: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
}

export function DocStatusBadge({ doc }: { doc: GeneratedDoc }) {
  const busy = doc.status === 'queued' || doc.status === 'running'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[doc.status]}`}>
      {es.docs.status[doc.status]}
      {busy && doc.progress > 0 ? ` ${Math.round(doc.progress * 100)} %` : ''}
    </span>
  )
}

/** Diálogo para generar apuntes o un resumen a partir de fuentes de una asignatura. */
export function GenerateDialog({
  open,
  kind,
  subjectId,
  onClose,
}: {
  open: boolean
  kind: DocKind
  subjectId: string
  onClose: () => void
}) {
  const navigate = useNavigate()
  const sources = useQuery(
    () =>
      open
        ? api.listSources({ subject_id: subjectId, status: 'ready', limit: 200 })
        : Promise.resolve(null),
    [open, subjectId],
  )
  const [picked, setPicked] = useState<string[]>([])
  const [detail, setDetail] = useState<DocDetail>('medium')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const usable = sources.data?.items.filter((s) => s.version != null) ?? []

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  const askCloud = useCloudConsent()

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const consent = await askCloud({ kind: 'docs', subject_id: subjectId, source_ids: picked })
      if (consent === false) return
      const doc = await api.createDocument(subjectId, {
        kind,
        detail,
        source_ids: picked,
        title: title.trim() || null,
        consent_id: consent,
      })
      onClose()
      navigate({ name: 'document', id: doc.id, kind })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={kind === 'notes' ? es.docs.newNotes : es.docs.newSummary}
      onClose={onClose}
    >
      <div className="space-y-4">
        <fieldset>
          <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {es.docs.sources}
          </legend>
          {sources.loading && !sources.data ? (
            <Loading />
          ) : usable.length === 0 ? (
            <p className="mt-1 text-sm text-zinc-500">{es.docs.noSources}</p>
          ) : (
            <ul className="mt-1 max-h-52 space-y-1 overflow-y-auto rounded-md border border-zinc-200 p-2 dark:border-zinc-800">
              {usable.map((s) => (
                <li key={s.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={picked.includes(s.id)}
                      onChange={() => toggle(s.id)}
                    />
                    <span className="truncate">{s.title}</span>
                    <span className="ml-auto shrink-0 text-xs text-zinc-500">
                      {es.kinds[s.kind]}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1 text-xs text-zinc-500">{es.docs.sourcesHint}</p>
        </fieldset>
        <fieldset className="flex gap-4">
          <legend className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {es.docs.detail}
          </legend>
          {(Object.keys(es.docs.details) as DocDetail[]).map((d) => (
            <label key={d} className="flex items-center gap-1.5 text-sm">
              <input
                type="radio"
                name="detail"
                checked={detail === d}
                onChange={() => setDetail(d)}
              />
              {es.docs.details[d]}
            </label>
          ))}
        </fieldset>
        <Field label={`${es.docs.titleField} ${es.common.optional}`} hint={es.docs.titleHint}>
          <input
            className={inputClass}
            value={title}
            maxLength={300}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <p className="text-xs text-zinc-500">{es.docs.queuedHint}</p>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{es.common.cancel}</Button>
          <Button
            variant="primary"
            disabled={busy || picked.length === 0}
            onClick={() => void submit()}
          >
            {busy ? es.docs.generating : es.docs.generate}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/** Botones rápidos en una fuente: apuntes o resumen de esa fuente con detalle intermedio. */
export function QuickGenerate({ subjectId, sourceId }: { subjectId: string; sourceId: string }) {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const askCloud = useCloudConsent()
  const go = async (kind: DocKind) => {
    setError(null)
    try {
      const consent = await askCloud({
        kind: 'docs',
        subject_id: subjectId,
        source_ids: [sourceId],
      })
      if (consent === false) return
      const doc = await api.createDocument(subjectId, {
        kind,
        detail: 'medium',
        source_ids: [sourceId],
        consent_id: consent,
      })
      navigate({ name: 'document', id: doc.id, kind })
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <span className="flex items-center gap-2" title={es.docs.quickHint}>
      <Button onClick={() => void go('notes')}>{es.docs.quickNotes}</Button>
      <Button onClick={() => void go('summary')}>{es.docs.quickSummary}</Button>
      {error && <ErrorText>{error}</ErrorText>}
    </span>
  )
}

export function DocList({ docs, kind }: { docs: GeneratedDoc[]; kind: DocKind }) {
  const navigate = useNavigate()
  return (
    <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {docs.map((d) => (
        <li key={d.id}>
          <button
            type="button"
            onClick={() => navigate({ name: 'document', id: d.id, kind })}
            className="flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{d.title}</div>
              <div className="text-xs text-zinc-500">
                {es.docs.details[d.detail]} · {formatDate(d.created_at)}
                {isBusy(d) && d.message ? ` · ${d.message}` : ''}
              </div>
            </div>
            <DocStatusBadge doc={d} />
          </button>
        </li>
      ))}
    </ul>
  )
}
