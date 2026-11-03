import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  ErrorText,
  Field,
  inputClass,
  PageHeader,
  StatusBadge,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, fileName, files, type ImportResult, type SourceStatus } from '../lib/api'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { unitTree } from '../lib/subjects'

interface Row {
  name: string
  ok: boolean
  message: string
  sourceId?: string
  /** Estado de procesamiento de un archivo importado con éxito (se actualiza solo). */
  status?: SourceStatus
}

interface ErrBody {
  id?: string
  error?: { code?: string; message?: string; details?: { source_id?: string } }
}

function toRow(r: ImportResult): Row {
  const body = (r.body ?? {}) as ErrBody
  if (r.status === 201)
    return {
      name: fileName(r.path),
      ok: true,
      message: es.import.queued,
      sourceId: body.id,
      status: 'pending',
    }
  return {
    name: fileName(r.path),
    ok: false,
    message: body.error?.message ?? es.common.unexpected,
    sourceId: body.error?.code === 'duplicate' ? body.error.details?.source_id : undefined,
  }
}

function PasteForm({ subjectId, unitIds }: { subjectId: string; unitIds: string[] }) {
  const [kind, setKind] = useState<'paste' | 'note'>('note')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const navigate = useNavigate()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      const s = await api.createTextSource({
        subject_id: subjectId,
        kind,
        title,
        text,
        unit_ids: unitIds,
        session_ids: [],
      })
      setDone(s.id)
      setTitle('')
      setText('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3">
      <div className="flex gap-4 text-sm">
        {(['note', 'paste'] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5">
            <input
              type="radio"
              name="paste-kind"
              checked={kind === k}
              onChange={() => setKind(k)}
            />
            {es.import.pasteKind[k]}
          </label>
        ))}
      </div>
      <Field label={es.import.pasteTitle}>
        <input
          className={inputClass}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={300}
        />
      </Field>
      <Field label={es.import.pasteText} hint={es.import.pasteHint}>
        <textarea
          className={`${inputClass} font-mono`}
          rows={8}
          value={text}
          onChange={(e) => setText(e.target.value)}
          required
        />
      </Field>
      <ErrorText>{error}</ErrorText>
      {done && (
        <p className="text-sm text-emerald-700 dark:text-emerald-400">
          {es.import.pasteDone}{' '}
          <button
            type="button"
            className="underline"
            onClick={() => navigate({ name: 'source', id: done })}
          >
            {es.import.viewExisting}
          </button>
        </p>
      )}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" disabled={!title.trim() || !text.trim()}>
          {es.import.pasteSave}
        </Button>
      </div>
    </form>
  )
}

export function Import({
  subjectId: initialSubject,
  unitId,
}: {
  subjectId?: string
  unitId?: string
}) {
  const subjects = useQuery(() => api.listSubjects(false), [])
  const [subjectId, setSubjectId] = useState(initialSubject ?? '')
  const detail = useQuery(
    () => (subjectId ? api.getSubject(subjectId) : Promise.resolve(null)),
    [subjectId],
  )
  const [unitIds, setUnitIds] = useState<string[]>(unitId ? [unitId] : [])
  const [hover, setHover] = useState(false)
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<string | null>(null)
  const [savedCount, setSavedCount] = useState(0)
  const [pasteOpen, setPasteOpen] = useState(false)
  const navigate = useNavigate()

  // Actualiza el estado de los archivos recién importados hasta que terminen de procesarse.
  const processing = rows.some((r) => r.status === 'pending' || r.status === 'processing')
  const rowsRef = useRef(rows)
  useEffect(() => {
    rowsRef.current = rows
  }, [rows])
  useEffect(() => {
    if (!processing) return
    const ac = new AbortController()
    const t = window.setInterval(() => {
      const ids = rowsRef.current
        .filter((r) => r.sourceId && (r.status === 'pending' || r.status === 'processing'))
        .map((r) => r.sourceId!)
      void Promise.all(ids.map((id) => api.getSource(id).catch(() => null))).then((list) => {
        if (ac.signal.aborted) return
        setRows((rs) =>
          rs.map((r) => {
            const src = list.find((x) => x?.id === r.sourceId)
            if (!src || !r.ok) return r
            const message =
              src.status === 'ready'
                ? es.import.ready
                : src.status === 'failed'
                  ? (src.error_message ?? es.source.failed)
                  : r.message
            return { ...r, status: src.status, message, ok: src.status !== 'failed' }
          }),
        )
      })
    }, 1500)
    ac.signal.addEventListener('abort', () => window.clearInterval(t))
    return () => ac.abort()
  }, [processing])

  // Si solo hay una asignatura, se elige sola.
  const only = subjects.data?.length === 1 ? subjects.data[0].id : ''
  const effectiveSubject = subjectId || only

  // El destino actual, accesible desde el listener de arrastrar y soltar.
  const target = useRef({ subjectId: effectiveSubject, unitIds })
  useEffect(() => {
    target.current = { subjectId: effectiveSubject, unitIds }
  }, [effectiveSubject, unitIds])

  const importPaths = async (paths: string[]) => {
    if (!paths.length || !files) return
    const { subjectId: sid, unitIds: units } = target.current
    if (!sid) {
      setError(es.import.chooseSubject)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const results = await files.importPaths({ subject_id: sid, unit_ids: units }, paths)
      const newRows = results.map(toRow)
      setRows((prev) => [...newRows, ...prev])
      setSavedCount(newRows.filter((r) => r.ok).length)
    } catch (e) {
      setError(typeof e === 'string' ? e : errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  const importRef = useRef(importPaths)
  useEffect(() => {
    importRef.current = importPaths
  })

  useEffect(() => {
    if (!files) return
    const ac = new AbortController()
    void files
      .onDrop((state) => {
        if (state === 'enter') setHover(true)
        else if (state === 'leave') setHover(false)
        else {
          setHover(false)
          void importRef.current(state.paths)
        }
      })
      .then((unlisten) => {
        if (ac.signal.aborted) unlisten()
        else ac.signal.addEventListener('abort', unlisten)
      })
    return () => ac.abort()
  }, [])

  const pick = async () => {
    if (!files) return
    try {
      await importPaths(await files.pick())
    } catch (e) {
      setError(typeof e === 'string' ? e : errorMessage(e))
    }
  }

  const toggleUnit = (id: string) =>
    setUnitIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]))

  return (
    <div className="mx-auto max-w-4xl px-10 py-10">
      <PageHeader title={es.import.title} subtitle={es.import.subtitle} />
      {subjects.data?.length === 0 ? (
        <Card>
          <p className="text-sm">{es.import.needSubject}</p>
          <Button className="mt-3" variant="primary" onClick={() => navigate({ name: 'subjects' })}>
            {es.subjects.new}
          </Button>
        </Card>
      ) : (
        <div className="space-y-6">
          <Card className="space-y-4">
            <Field label={es.import.subject}>
              <select
                className={inputClass}
                value={effectiveSubject}
                onChange={(e) => {
                  setSubjectId(e.target.value)
                  setUnitIds([])
                }}
              >
                <option value="">{es.import.chooseSubject}</option>
                {subjects.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            {detail.data && detail.data.units.length > 0 && (
              <fieldset>
                <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  {es.import.topics}
                </legend>
                <p className="mb-2 text-xs text-zinc-500">{es.import.topicsHint}</p>
                <div className="max-h-48 space-y-1 overflow-y-auto">
                  {unitTree(detail.data.units).map(({ unit, depth }) => (
                    <label
                      key={unit.id}
                      className="flex items-center gap-2 text-sm"
                      style={{ paddingLeft: `${depth}rem` }}
                    >
                      <input
                        type="checkbox"
                        checked={unitIds.includes(unit.id)}
                        onChange={() => toggleUnit(unit.id)}
                      />
                      <span className="text-xs text-zinc-500">
                        {es.subject.unitKind[unit.kind]}
                      </span>
                      {unit.title}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}
          </Card>

          {files ? (
            <div
              className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
                hover
                  ? 'border-accent-500 bg-accent-50 dark:bg-accent-700/10'
                  : 'border-zinc-300 dark:border-zinc-700'
              }`}
            >
              <p className="font-medium">{busy ? es.import.importing : es.import.drop}</p>
              <p className="my-2 text-sm text-zinc-500">{es.import.dropHint}</p>
              <Button
                variant="primary"
                disabled={busy || !effectiveSubject}
                onClick={() => void pick()}
              >
                {es.import.pick}
              </Button>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">{es.import.webOnly}</p>
          )}
          <ErrorText>{error}</ErrorText>
          {savedCount > 0 && (
            <div
              role="status"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200"
            >
              <span>✓ {es.import.savedNotice(savedCount)}</span>
              <Button onClick={() => navigate({ name: 'library', subjectId: effectiveSubject })}>
                {es.import.openLibrary}
              </Button>
            </div>
          )}

          {rows.length > 0 && (
            <Card>
              <h2 className="mb-2 font-medium">{es.import.results}</h2>
              <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                {rows.map((r, i) => (
                  <li key={i} className="flex items-start gap-3 py-2">
                    <span aria-hidden className={r.ok ? 'text-emerald-600' : 'text-red-600'}>
                      {r.ok ? '✓' : '✕'}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{r.name}</div>
                      <div className={r.ok ? 'text-zinc-500' : 'text-red-600 dark:text-red-400'}>
                        {r.message}
                      </div>
                    </div>
                    {r.status && <StatusBadge status={r.status} />}
                    {r.sourceId && (
                      <Button
                        variant="ghost"
                        onClick={() => navigate({ name: 'source', id: r.sourceId! })}
                      >
                        {es.import.viewExisting}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {effectiveSubject &&
            (pasteOpen ? (
              <Card>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="font-medium">{es.import.paste}</h2>
                  <Button variant="ghost" onClick={() => setPasteOpen(false)}>
                    {es.import.pasteHide}
                  </Button>
                </div>
                <PasteForm subjectId={effectiveSubject} unitIds={unitIds} />
              </Card>
            ) : (
              <Button variant="ghost" onClick={() => setPasteOpen(true)}>
                {es.import.pasteToggle}
              </Button>
            ))}
        </div>
      )}
    </div>
  )
}
