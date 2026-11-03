import { useState } from 'react'
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
} from '../components/ui'
import { es } from '../i18n/es'
import { api, type Session, type SubjectDetail as Detail, type Unit } from '../lib/api'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { UNIT_RANK as RANK, type UnitKind, unitTree } from '../lib/subjects'
import { SubjectForm } from './Subjects'

function UnitForm({
  subjectId,
  units,
  parentId,
  onDone,
}: {
  subjectId: string
  units: Unit[]
  parentId: string | null
  onDone: () => void
}) {
  const parent = units.find((u) => u.id === parentId)
  const allowed = (Object.keys(RANK) as UnitKind[]).filter(
    (k) => !parent || RANK[k] > RANK[parent.kind],
  )
  const [kind, setKind] = useState<UnitKind>(allowed.includes('topic') ? 'topic' : allowed[0])
  const [title, setTitle] = useState('')
  const [parentSel, setParentSel] = useState(parentId ?? '')
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.createUnit(subjectId, {
        kind,
        title,
        parent_id: parentSel || null,
        position: units.length,
      })
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  const parents = unitTree(units).filter(({ unit }) => RANK[unit.kind] < RANK[kind])
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4">
      <Field label={es.subject.kind}>
        <select
          className={inputClass}
          value={kind}
          onChange={(e) => setKind(e.target.value as UnitKind)}
        >
          {(Object.keys(RANK) as UnitKind[]).map((k) => (
            <option key={k} value={k}>
              {es.subject.unitKind[k]}
            </option>
          ))}
        </select>
      </Field>
      <Field label={es.subject.unitTitle}>
        <input
          className={inputClass}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={200}
          autoFocus
        />
      </Field>
      <Field label={es.subject.parent}>
        <select
          className={inputClass}
          value={parentSel}
          onChange={(e) => setParentSel(e.target.value)}
        >
          <option value="">{es.subject.noParent}</option>
          {parents.map(({ unit, depth }) => (
            <option key={unit.id} value={unit.id}>
              {'  '.repeat(depth)}
              {es.subject.unitKind[unit.kind]}: {unit.title}
            </option>
          ))}
        </select>
      </Field>
      <ErrorText>{error}</ErrorText>
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>{es.common.cancel}</Button>
        <Button type="submit" variant="primary" disabled={!title.trim()}>
          {es.common.add}
        </Button>
      </div>
    </form>
  )
}

function SessionForm({ subject, onDone }: { subject: Detail; onDone: () => void }) {
  const [kind, setKind] = useState<Session['kind']>('class')
  const [title, setTitle] = useState('')
  const [heldAt, setHeldAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [unitId, setUnitId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.createSession(subject.id, {
        kind,
        title,
        held_at: heldAt || null,
        unit_id: unitId || null,
      })
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4">
      <Field label={es.subject.kind}>
        <select
          className={inputClass}
          value={kind}
          onChange={(e) => setKind(e.target.value as Session['kind'])}
        >
          <option value="class">{es.subject.sessionKind.class}</option>
          <option value="study">{es.subject.sessionKind.study}</option>
        </select>
      </Field>
      <Field label={es.subject.unitTitle}>
        <input
          className={inputClass}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={200}
          autoFocus
        />
      </Field>
      <Field label={es.subject.heldAt}>
        <input
          type="date"
          className={inputClass}
          value={heldAt}
          onChange={(e) => setHeldAt(e.target.value)}
        />
      </Field>
      <Field label={`${es.subject.unit} ${es.common.optional}`}>
        <select className={inputClass} value={unitId} onChange={(e) => setUnitId(e.target.value)}>
          <option value="">{es.common.none}</option>
          {unitTree(subject.units).map(({ unit, depth }) => (
            <option key={unit.id} value={unit.id}>
              {'  '.repeat(depth)}
              {unit.title}
            </option>
          ))}
        </select>
      </Field>
      <ErrorText>{error}</ErrorText>
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>{es.common.cancel}</Button>
        <Button type="submit" variant="primary" disabled={!title.trim()}>
          {es.common.add}
        </Button>
      </div>
    </form>
  )
}

function UnitRow({
  unit,
  depth,
  onChange,
  onAddChild,
}: {
  unit: Unit
  depth: number
  onChange: () => void
  onAddChild: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(unit.title)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const save = async () => {
    try {
      await api.updateUnit(unit.id, { title })
      setEditing(false)
      setError(null)
      onChange()
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <li className="group py-1.5" style={{ paddingLeft: `${depth * 1.25}rem` }}>
      <div className="flex items-center gap-2">
        <span className="w-14 shrink-0 text-xs text-zinc-500">
          {es.subject.unitKind[unit.kind]}
        </span>
        {editing ? (
          <input
            className={`${inputClass} max-w-xs`}
            value={title}
            autoFocus
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void save()
              if (e.key === 'Escape') setEditing(false)
            }}
          />
        ) : (
          <button
            type="button"
            className="truncate text-sm hover:underline"
            onClick={() =>
              navigate({ name: 'library', subjectId: unit.subject_id, unitId: unit.id })
            }
          >
            {unit.title}
          </button>
        )}
        <div className="ml-auto flex gap-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
          {editing ? (
            <Button variant="ghost" onClick={() => void save()}>
              {es.common.save}
            </Button>
          ) : (
            <Button variant="ghost" onClick={() => setEditing(true)}>
              {es.common.edit}
            </Button>
          )}
          {unit.kind !== 'topic' && (
            <Button variant="ghost" onClick={onAddChild}>
              {es.subject.addChild}
            </Button>
          )}
          <ConfirmButton
            label={es.common.delete}
            title={es.subject.deleteUnit(unit.title)}
            onConfirm={async () => {
              await api.deleteUnit(unit.id)
              onChange()
            }}
          />
        </div>
      </div>
      <ErrorText>{error}</ErrorText>
    </li>
  )
}

export function SubjectDetail({ id }: { id: string }) {
  const q = useQuery(() => api.getSubject(id), [id])
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [unitParent, setUnitParent] = useState<string | null | undefined>(undefined)
  const [addingSession, setAddingSession] = useState(false)

  if (!q.data) {
    return (
      <div className="mx-auto max-w-5xl px-10 py-10">
        {q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}
      </div>
    )
  }
  const s = q.data
  const reload = () => void q.reload()
  const archived = Boolean(s.archived_at)

  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <button
        type="button"
        className="mb-3 text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: 'subjects' })}
      >
        ← {es.subjects.title}
      </button>
      <PageHeader
        title={s.name}
        subtitle={[s.term, s.description, archived ? es.subjects.archived : null]
          .filter(Boolean)
          .join(' · ')}
        actions={
          <>
            <Button variant="primary" onClick={() => navigate({ name: 'import', subjectId: s.id })}>
              {es.subject.importHere}
            </Button>
            <Button onClick={() => navigate({ name: 'library', subjectId: s.id })}>
              {es.subject.materials}
            </Button>
            <Button onClick={() => setEditing(true)}>{es.common.edit}</Button>
            <Button
              onClick={() => void api.updateSubject(s.id, { archived: !archived }).then(reload)}
            >
              {archived ? es.subjects.unarchive : es.subjects.archive}
            </Button>
            <ConfirmButton
              label={es.common.delete}
              title={es.subjects.deleteTitle(s.name)}
              body={es.subjects.deleteBody}
              onConfirm={async () => {
                await api.deleteSubject(s.id)
                navigate({ name: 'subjects' })
              }}
            />
          </>
        }
      />
      <ErrorText>{q.error}</ErrorText>
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card>
          <div className="mb-1 flex items-center justify-between">
            <h2 className="font-medium">{es.subject.structure}</h2>
            <Button variant="ghost" onClick={() => setUnitParent(null)}>
              + {es.subject.addUnit}
            </Button>
          </div>
          <p className="mb-3 text-xs text-zinc-500">{es.subject.structureHint}</p>
          {s.units.length === 0 ? (
            <p className="text-sm text-zinc-500">{es.subject.noUnits}</p>
          ) : (
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {unitTree(s.units).map(({ unit, depth }) => (
                <UnitRow
                  key={unit.id}
                  unit={unit}
                  depth={depth}
                  onChange={reload}
                  onAddChild={() => setUnitParent(unit.id)}
                />
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-medium">{es.subject.sessions}</h2>
            <Button variant="ghost" onClick={() => setAddingSession(true)}>
              + {es.subject.addSession}
            </Button>
          </div>
          {s.sessions.length === 0 ? (
            <p className="text-sm text-zinc-500">{es.subject.noSessions}</p>
          ) : (
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {s.sessions.map((x) => (
                <li key={x.id} className="flex items-center gap-2 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{x.title}</div>
                    <div className="text-xs text-zinc-500">
                      {es.subject.sessionKind[x.kind]} ·{' '}
                      {x.held_at ? formatDate(x.held_at).split(',')[0] : '—'}
                    </div>
                  </div>
                  <ConfirmButton
                    label={es.common.delete}
                    title={es.subject.deleteSession(x.title)}
                    onConfirm={async () => {
                      await api.deleteSession(x.id)
                      reload()
                    }}
                  />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={editing} title={es.common.edit} onClose={() => setEditing(false)}>
        <SubjectForm
          initial={s}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false)
            reload()
          }}
        />
      </Modal>
      <Modal
        open={unitParent !== undefined}
        title={es.subject.addUnit}
        onClose={() => setUnitParent(undefined)}
      >
        <UnitForm
          key={String(unitParent)}
          subjectId={s.id}
          units={s.units}
          parentId={unitParent ?? null}
          onDone={() => {
            setUnitParent(undefined)
            reload()
          }}
        />
      </Modal>
      <Modal
        open={addingSession}
        title={es.subject.addSession}
        onClose={() => setAddingSession(false)}
      >
        <SessionForm
          subject={s}
          onDone={() => {
            setAddingSession(false)
            reload()
          }}
        />
      </Modal>
    </div>
  )
}
