import { useState } from 'react'
import {
  Button,
  Card,
  ErrorText,
  Field,
  inputClass,
  Loading,
  Modal,
  PageHeader,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, type Subject } from '../lib/api'
import { useNavigate } from '../lib/nav'
import { SUBJECT_COLORS } from '../lib/subjects'
import { errorMessage, useQuery } from '../lib/useQuery'

export function SubjectForm({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: Subject
  onSaved: (s: Subject) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [term, setTerm] = useState(initial?.term ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [color, setColor] = useState(initial?.color ?? SUBJECT_COLORS[0])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = { name, term: term || null, description: description || null, color }
      onSaved(initial ? await api.updateSubject(initial.id, body) : await api.createSubject(body))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4">
      <Field label={es.subjects.name}>
        <input
          className={inputClass}
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={200}
          autoFocus
        />
      </Field>
      <Field label={`${es.subjects.term} ${es.common.optional}`} hint={es.subjects.termHint}>
        <input
          className={inputClass}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          maxLength={50}
        />
      </Field>
      <Field label={`${es.subjects.description} ${es.common.optional}`}>
        <textarea
          className={inputClass}
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={2000}
        />
      </Field>
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
          {es.subjects.color}
        </legend>
        <div className="flex gap-2">
          {SUBJECT_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              aria-label={c}
              aria-pressed={color === c}
              onClick={() => setColor(c)}
              className={`size-6 rounded-full ${color === c ? 'ring-2 ring-zinc-900 ring-offset-2 dark:ring-white dark:ring-offset-zinc-900' : ''}`}
              style={{ background: c }}
            />
          ))}
        </div>
      </fieldset>
      <ErrorText>{error}</ErrorText>
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>{es.common.cancel}</Button>
        <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
          {busy ? es.common.saving : initial ? es.common.save : es.common.create}
        </Button>
      </div>
    </form>
  )
}

export function Subjects() {
  const [archived, setArchived] = useState(false)
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()
  const q = useQuery(() => api.listSubjects(archived), [archived])

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <PageHeader
        title={es.subjects.title}
        subtitle={es.subjects.subtitle}
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            {es.subjects.new}
          </Button>
        }
      />
      <label className="mb-4 flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
        <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
        {es.subjects.showArchived}
      </label>
      <ErrorText>{q.error}</ErrorText>
      {q.loading && !q.data && <Loading />}
      {q.data?.length === 0 && <p className="text-sm text-zinc-500">{es.subjects.empty}</p>}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {q.data?.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              className="block w-full text-left"
              onClick={() => navigate({ name: 'subject', id: s.id })}
            >
              <Card className="h-full transition-colors hover:border-accent-500">
                <div className="flex items-center gap-2">
                  <span
                    className="size-3 shrink-0 rounded-full"
                    style={{ background: s.color ?? SUBJECT_COLORS[0] }}
                  />
                  <h2 className="truncate font-medium">{s.name}</h2>
                </div>
                {s.term && <p className="mt-1 text-xs text-zinc-500">{s.term}</p>}
                <p className="mt-3 text-xs text-zinc-500">
                  {es.subjects.counts(s.source_count ?? 0, s.unit_count ?? 0)}
                </p>
              </Card>
            </button>
          </li>
        ))}
      </ul>
      <Modal open={creating} title={es.subjects.new} onClose={() => setCreating(false)}>
        <SubjectForm
          onCancel={() => setCreating(false)}
          onSaved={(s) => {
            setCreating(false)
            navigate({ name: 'subject', id: s.id })
          }}
        />
      </Modal>
    </div>
  )
}
