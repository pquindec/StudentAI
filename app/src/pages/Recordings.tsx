import { useEffect, useState } from 'react'
import { LevelMeter } from '../components/RecordingBar'
import { SttPanel } from '../components/SttPanel'
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
import { api, native } from '../lib/api'
import { formatDate, formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { importedSourceId, useRecording } from '../lib/recording'
import { unitTree } from '../lib/subjects'
import { useQuery } from '../lib/useQuery'

const SUBJECT_KEY = 'recording.subject'

/** Asignatura de la última grabación (comodidad local; si falla el almacenamiento, no pasa nada). */
function lastSubject(): string {
  try {
    return localStorage.getItem(SUBJECT_KEY) ?? ''
  } catch {
    return ''
  }
}

function rememberSubject(id: string) {
  try {
    localStorage.setItem(SUBJECT_KEY, id)
  } catch {
    // sin almacenamiento local: se elegirá la primera asignatura
  }
}

function NewRecording() {
  const rec = useRecording()
  const subjects = useQuery(() => api.listSubjects(false), [])
  const devices = useQuery(() => (native ? native.devices() : Promise.resolve([])), [])
  const [subjectId, setSubjectId] = useState(lastSubject)
  const [unitIds, setUnitIds] = useState<string[]>([])
  const [title, setTitle] = useState(() => es.recording.defaultName(new Date()))
  const [deviceId, setDeviceId] = useState('')
  // Siempre hay una asignatura elegida: la de la última grabación o, si no, la primera.
  const known = subjects.data?.some((s) => s.id === subjectId)
  const effectiveSubject = (known ? subjectId : subjects.data?.[0]?.id) ?? ''
  const detail = useQuery(
    () => (effectiveSubject ? api.getSubject(effectiveSubject) : Promise.resolve(null)),
    [effectiveSubject],
  )
  const navigate = useNavigate()
  const active = rec.status.state !== 'idle'

  if (subjects.data?.length === 0) {
    return (
      <Card>
        <p className="text-sm">{es.recording.needSubject}</p>
        <Button className="mt-3" variant="primary" onClick={() => navigate({ name: 'subjects' })}>
          {es.subjects.new}
        </Button>
      </Card>
    )
  }

  if (active) {
    return (
      <Card className="space-y-3">
        <h2 className="font-medium">{rec.status.title}</h2>
        <div className="flex items-center gap-4">
          <span className="font-mono text-3xl tabular-nums">
            {formatDuration(rec.status.elapsed_ms)}
          </span>
          <div className="rounded bg-red-600 px-2 py-1">
            <LevelMeter level={rec.status.state === 'paused' ? 0 : rec.status.level} />
          </div>
          <span className="text-xs text-zinc-500">{rec.status.device}</span>
        </div>
        <p className="text-xs text-zinc-500">{es.recording.silentHint}</p>
        <div className="flex gap-2">
          <Button disabled={rec.busy} onClick={() => void rec.pause(rec.status.state === 'paused')}>
            {rec.status.state === 'paused' ? es.recording.resume : es.recording.pause}
          </Button>
          <Button variant="danger" disabled={rec.busy} onClick={() => void rec.stop()}>
            {rec.busy ? es.recording.stopping : es.recording.stop}
          </Button>
        </div>
        <ErrorText>{rec.status.error ?? rec.error}</ErrorText>
      </Card>
    )
  }

  const toggleUnit = (id: string) =>
    setUnitIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]))

  return (
    <Card className="space-y-4">
      <h2 className="font-medium">{es.recording.newTitle}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={es.recording.subject}>
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
        <Field label={es.recording.device}>
          <select
            className={inputClass}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
          >
            <option value="">{es.recording.defaultDevice}</option>
            {devices.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={es.recording.name}>
        <input
          className={inputClass}
          value={title}
          maxLength={300}
          onChange={(e) => setTitle(e.target.value)}
        />
      </Field>
      {detail.data && detail.data.units.length > 0 && (
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {es.recording.units}
          </legend>
          <div className="max-h-40 space-y-1 overflow-y-auto">
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
                {unit.title}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <ErrorText>{rec.error ?? devices.error}</ErrorText>
      {!title.trim() && <p className="text-xs text-zinc-500">{es.recording.needTitle}</p>}
      <p className="text-xs text-zinc-500">{es.recording.independent}</p>
      <Button
        variant="primary"
        className="!bg-red-600 hover:!bg-red-700"
        disabled={rec.busy || !effectiveSubject || !title.trim()}
        onClick={() => {
          rememberSubject(effectiveSubject)
          void rec.start(
            { subject_id: effectiveSubject, title: title.trim(), unit_ids: unitIds },
            deviceId || undefined,
          )
        }}
      >
        ● {rec.busy ? es.recording.starting : es.recording.start}
      </Button>
    </Card>
  )
}

function LastResult() {
  const rec = useRecording()
  const navigate = useNavigate()
  const r = rec.lastResult
  if (!r) return null
  const sid = importedSourceId(r)
  const failure = (r.body as { error?: { message?: string } } | null)?.error?.message
  return (
    <div
      role="status"
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3 text-sm ${
        sid
          ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200'
          : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-200'
      }`}
    >
      <span>
        {sid ? `✓ ${es.recording.saved}` : (failure ?? es.common.unexpected)}
        {r.warning && <span className="block text-xs">{r.warning}</span>}
      </span>
      {sid && (
        <Button onClick={() => navigate({ name: 'source', id: sid })}>{es.recording.open}</Button>
      )}
    </div>
  )
}

function SavedRecordings() {
  const navigate = useNavigate()
  const rec = useRecording()
  const list = useQuery(
    () => api.listSources({ kind: 'recording', limit: 20 }),
    [rec.lastResult?.recording_id],
  )
  // Mientras se transcribe alguna, se refresca hasta que pase a «Listo» (o falle).
  const busy = list.data?.items.some((s) => s.status === 'pending' || s.status === 'processing')
  const { reload } = list
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => void reload(), 2000)
    return () => window.clearInterval(t)
  }, [busy, reload])
  return (
    <Card>
      <h2 className="mb-3 font-medium">{es.recording.list}</h2>
      {list.data?.items.length === 0 && (
        <p className="text-sm text-zinc-500">{es.recording.empty}</p>
      )}
      <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {list.data?.items.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              className="flex w-full items-center gap-3 py-2 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-900"
              onClick={() => navigate({ name: 'source', id: s.id })}
            >
              <span className="min-w-0 flex-1 truncate font-medium">{s.title}</span>
              <span className="text-xs text-zinc-500">{formatDuration(s.duration_ms)}</span>
              <span className="text-xs text-zinc-500">{formatDate(s.imported_at)}</span>
              <StatusBadge status={s.status} />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function Recordings() {
  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <PageHeader title={es.recording.title} subtitle={es.recording.subtitle} />
      {native ? (
        <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
          <div className="space-y-6">
            <LastResult />
            <NewRecording />
            <SavedRecordings />
          </div>
          <SttPanel />
        </div>
      ) : (
        <p className="text-sm text-zinc-500">{es.recording.webOnly}</p>
      )}
    </div>
  )
}
