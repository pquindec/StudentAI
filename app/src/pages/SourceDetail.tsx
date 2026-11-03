import { useEffect, useRef, useState } from 'react'
import { AudioPanel, TranscriptView } from '../components/Transcript'
import {
  Button,
  Card,
  ConfirmButton,
  ErrorText,
  Field,
  inputClass,
  Loading,
  Modal,
  PageHeader,
  StatusBadge,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, ApiError, type Source, type SourceContent } from '../lib/api'
import { formatBytes, formatDate, formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { isAudio, unitTree } from '../lib/subjects'

/**
 * Vista previa del texto por segmentos. El contenido importado se muestra como TEXTO
 * (React escapa todo): nunca se interpreta como HTML ni como instrucciones.
 */
function pageMarkers(content: SourceContent): boolean[] {
  const marks: boolean[] = []
  let page: number | null = null
  for (const seg of content.segments) {
    marks.push(seg.page != null && seg.page !== page)
    if (seg.page != null) page = seg.page
  }
  return marks
}

function Preview({ content }: { content: SourceContent }) {
  const marks = pageMarkers(content)
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {content.segments.map((seg, i) => {
        const marker = marks[i]
        return (
          <div key={seg.ordinal}>
            {marker && (
              <div className="my-4 border-t border-dashed border-zinc-300 pt-1 text-xs text-zinc-400 dark:border-zinc-700">
                {es.source.page(seg.page!)}
              </div>
            )}
            {seg.kind === 'heading' ? (
              <p className={`font-semibold ${seg.level === 1 ? 'text-lg' : 'text-base'}`}>
                {seg.text.replace(/^#+\s*/, '')}
              </p>
            ) : seg.kind === 'table' ? (
              <pre className="overflow-x-auto rounded bg-zinc-50 p-2 font-mono text-xs dark:bg-zinc-900">
                {seg.text}
              </pre>
            ) : (
              <p className="whitespace-pre-wrap">{seg.text}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

function Editor({
  source,
  content,
  onSaved,
  onCancel,
  hint,
}: {
  source: Source
  content: SourceContent
  onSaved: () => void
  onCancel: () => void
  hint?: string
}) {
  const [text, setText] = useState(content.text)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.saveContent(source.id, text, content.version)
      onSaved()
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === 'version_conflict'
          ? es.source.conflict
          : errorMessage(e),
      )
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-500">{es.source.editHint}</p>
      {hint && <p className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{hint}</p>}
      <textarea
        aria-label={es.source.edit}
        className={`${inputClass} min-h-[28rem] font-mono text-xs leading-relaxed`}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <ErrorText>{error}</ErrorText>
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>{es.common.cancel}</Button>
        <Button
          variant="primary"
          disabled={busy || text === content.text || !text.trim()}
          onClick={() => void save()}
        >
          {busy ? es.common.saving : es.common.save}
        </Button>
      </div>
    </div>
  )
}

function LinksForm({ source, onDone }: { source: Source; onDone: () => void }) {
  const subject = useQuery(() => api.getSubject(source.subject_id), [source.subject_id])
  const [ids, setIds] = useState<string[]>(source.unit_ids)
  const [title, setTitle] = useState(source.title)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    try {
      await api.updateSource(source.id, { title, unit_ids: ids })
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <div className="space-y-4">
      <Field label={es.source.rename}>
        <input
          className={inputClass}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={300}
        />
      </Field>
      <fieldset className="max-h-64 space-y-1 overflow-y-auto">
        <legend className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
          {es.source.links}
        </legend>
        {subject.data &&
          unitTree(subject.data.units).map(({ unit, depth }) => (
            <label
              key={unit.id}
              className="flex items-center gap-2 text-sm"
              style={{ paddingLeft: `${depth}rem` }}
            >
              <input
                type="checkbox"
                checked={ids.includes(unit.id)}
                onChange={() =>
                  setIds((x) =>
                    x.includes(unit.id) ? x.filter((i) => i !== unit.id) : [...x, unit.id],
                  )
                }
              />
              {unit.title}
            </label>
          ))}
      </fieldset>
      <ErrorText>{error}</ErrorText>
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>{es.common.cancel}</Button>
        <Button variant="primary" disabled={!title.trim()} onClick={() => void save()}>
          {es.common.save}
        </Button>
      </div>
    </div>
  )
}

export function SourceDetail({ id }: { id: string }) {
  const navigate = useNavigate()
  const source = useQuery(() => api.getSource(id), [id])
  const [version, setVersion] = useState<number | undefined>(undefined)
  const s = source.data
  const ready = s?.status === 'ready' && s.version != null
  const content = useQuery(
    () => (ready ? api.getContent(id, version) : Promise.resolve(null)),
    [id, version, ready, s?.version],
  )
  const subject = useQuery(
    () => (s ? api.getSubject(s.subject_id) : Promise.resolve(null)),
    [s?.subject_id],
  )
  const [editing, setEditing] = useState(false)
  const [linking, setLinking] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [currentMs, setCurrentMs] = useState(0)
  const seek = (ms: number) => {
    const a = audioRef.current
    if (!a) return
    a.currentTime = ms / 1000
    void a.play()
  }

  // Refresca mientras se procesa.
  const pending = s?.status === 'pending' || s?.status === 'processing'
  const { reload } = source
  useEffect(() => {
    if (!pending) return
    const t = window.setInterval(() => void reload(), 1500)
    return () => window.clearInterval(t)
  }, [pending, reload])

  if (!s) {
    return (
      <div className="mx-auto max-w-5xl px-10 py-10">
        {source.error ? <ErrorText>{source.error}</ErrorText> : <Loading />}
      </div>
    )
  }

  const unitTitle = new Map(subject.data?.units.map((u) => [u.id, u.title]))
  const meta = s.metadata as Record<string, unknown>
  const warnings = Array.isArray(meta.warnings) ? (meta.warnings as string[]) : []
  const isOld = content.data != null && s.version != null && content.data.version !== s.version
  const audio = isAudio(s)
  const timed = content.data?.segments.some((x) => x.start_ms != null) ?? false

  const retry = async () => {
    setActionError(null)
    try {
      await api.retrySource(s.id)
      void reload()
    } catch (e) {
      setActionError(errorMessage(e))
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-10 py-10">
      <button
        type="button"
        className="mb-3 text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: 'library', subjectId: s.subject_id })}
      >
        ← {es.library.title}
      </button>
      <PageHeader
        title={s.title}
        subtitle={`${es.kinds[s.kind]} · ${subject.data?.name ?? ''}`}
        actions={
          <>
            <Button onClick={() => setLinking(true)}>{es.source.editLinks}</Button>
            <ConfirmButton
              label={es.common.delete}
              title={es.source.deleteTitle(s.title)}
              body={es.source.deleteBody}
              onConfirm={async () => {
                await api.deleteSource(s.id)
                navigate({ name: 'library', subjectId: s.subject_id })
              }}
            />
          </>
        }
      />
      <ErrorText>{actionError}</ErrorText>
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Card className="min-w-0">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <h2 className="font-medium">{es.source.content}</h2>
            {content.data && content.data.versions.length > 1 && (
              <select
                aria-label={es.source.content}
                className={`${inputClass} w-auto`}
                value={content.data.version}
                onChange={(e) => {
                  setEditing(false)
                  setVersion(Number(e.target.value))
                }}
              >
                {content.data.versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    {es.source.version(v.version)} — {es.source.origin[v.origin]} ·{' '}
                    {formatDate(v.created_at)}
                  </option>
                ))}
              </select>
            )}
            {ready && content.data && !editing && !isOld && (
              <Button className="ml-auto" onClick={() => setEditing(true)}>
                {es.source.edit}
              </Button>
            )}
          </div>
          {pending && <p className="text-sm text-zinc-500">{es.source.processing}</p>}
          {s.status === 'failed' && (
            <div className="space-y-2">
              <p className="text-sm font-medium text-red-600 dark:text-red-400">
                {es.source.failed}
              </p>
              <p className="text-sm">{s.error_message}</p>
              <Button onClick={() => void retry()}>{es.source.retry}</Button>
            </div>
          )}
          {s.status === 'cancelled' && (
            <Button onClick={() => void retry()}>{es.source.retry}</Button>
          )}
          {s.status === 'ready' && !audio && s.version == null && (
            <p className="text-sm text-zinc-500">{es.source.noContent}</p>
          )}
          {s.needs_review && !editing && (
            <p className="mb-3 text-sm text-amber-700 dark:text-amber-400">
              {es.source.needsReview}
            </p>
          )}
          {isOld && <p className="mb-3 text-xs text-zinc-500">{es.source.readOnlyOld}</p>}
          <ErrorText>{content.error}</ErrorText>
          {content.data &&
            (editing ? (
              <Editor
                source={s}
                content={content.data}
                onCancel={() => setEditing(false)}
                onSaved={() => {
                  setEditing(false)
                  setVersion(undefined)
                  void reload()
                }}
                hint={timed ? es.transcript.editHint : undefined}
              />
            ) : timed ? (
              <TranscriptView content={content.data} currentMs={currentMs} onSeek={seek} />
            ) : (
              <Preview content={content.data} />
            ))}
        </Card>

        <aside className="space-y-4 self-start lg:sticky lg:top-4">
          {audio && (
            <AudioPanel
              source={s}
              audioRef={audioRef}
              onTime={setCurrentMs}
              onChanged={() => {
                setVersion(undefined)
                void reload()
              }}
            />
          )}
          <Card>
            <h2 className="mb-3 text-sm font-medium">{es.source.details}</h2>
            <dl className="space-y-2 text-sm">
              <Row label={es.library.status} value={<StatusBadge status={s.status} />} />
              {s.original_name && <Row label={es.source.originalName} value={s.original_name} />}
              {s.size_bytes != null && (
                <Row label={es.source.size} value={formatBytes(s.size_bytes)} />
              )}
              {s.page_count != null && <Row label={es.source.pages} value={s.page_count} />}
              {s.duration_ms != null && (
                <Row label={es.source.duration} value={formatDuration(s.duration_ms)} />
              )}
              {typeof meta.encoding === 'string' && (
                <Row label={es.source.encoding} value={meta.encoding} />
              )}
              {s.char_count != null && (
                <Row label={es.source.content} value={es.source.chars(s.char_count)} />
              )}
              <Row label={es.source.imported} value={formatDate(s.imported_at)} />
              <Row
                label={es.source.links}
                value={
                  s.unit_ids.length
                    ? s.unit_ids.map((u) => unitTitle.get(u) ?? '…').join(', ')
                    : es.source.noLinks
                }
              />
            </dl>
          </Card>
          {warnings.length > 0 && (
            <Card>
              <h2 className="mb-2 text-sm font-medium">{es.source.warnings}</h2>
              <ul className="list-disc space-y-1 pl-4 text-xs text-zinc-600 dark:text-zinc-400">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </Card>
          )}
        </aside>
      </div>
      <Modal open={linking} title={es.source.editLinks} onClose={() => setLinking(false)}>
        <LinksForm
          source={s}
          onDone={() => {
            setLinking(false)
            void reload()
          }}
        />
      </Modal>
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-zinc-500">{label}</dt>
      <dd className="min-w-0 truncate text-right">{value}</dd>
    </div>
  )
}
