import { useEffect, useState } from 'react'
import { Button, ErrorText, inputClass, Loading, PageHeader, StatusBadge } from '../components/ui'
import { es } from '../i18n/es'
import { api, type Source, type SourceKind, type SourceStatus } from '../lib/api'
import { formatBytes, formatDate, formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { useQuery } from '../lib/useQuery'
import { unitTree } from '../lib/subjects'

const PAGE = 50

export function Library({
  subjectId: initialSubject,
  unitId: initialUnit,
}: {
  subjectId?: string
  unitId?: string
}) {
  const navigate = useNavigate()
  const [subjectId, setSubjectId] = useState(initialSubject ?? '')
  const [unitId, setUnitId] = useState(initialUnit ?? '')
  const [kind, setKind] = useState<SourceKind | ''>('')
  const [status, setStatus] = useState<SourceStatus | ''>('')
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [limit, setLimit] = useState(PAGE)

  // Espera a que el usuario deje de escribir antes de buscar.
  useEffect(() => {
    const t = window.setTimeout(() => setQ(text.trim()), 250)
    return () => window.clearTimeout(t)
  }, [text])

  const subjects = useQuery(() => api.listSubjects(false), [])
  const detail = useQuery(
    () => (subjectId ? api.getSubject(subjectId) : Promise.resolve(null)),
    [subjectId],
  )
  const list = useQuery(
    () =>
      api.listSources({
        subject_id: subjectId || undefined,
        unit_id: unitId || undefined,
        kind: kind || undefined,
        status: status || undefined,
        q: q || undefined,
        limit,
      }),
    [subjectId, unitId, kind, status, q, limit],
  )

  // Mientras haya elementos procesándose, refresca la lista.
  const busy = list.data?.items.some((s) => s.status === 'pending' || s.status === 'processing')
  const { reload } = list
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => void reload(), 2000)
    return () => window.clearInterval(t)
  }, [busy, reload])

  const subjectName = new Map(subjects.data?.map((s) => [s.id, s.name]))
  const select = `${inputClass} w-auto`

  return (
    <div className="mx-auto max-w-6xl px-10 py-10">
      <PageHeader
        title={es.library.title}
        subtitle={es.library.subtitle}
        actions={
          <Button
            variant="primary"
            onClick={() =>
              navigate({
                name: 'import',
                subjectId: subjectId || undefined,
                unitId: unitId || undefined,
              })
            }
          >
            {es.library.import}
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <input
          type="search"
          className={`${inputClass} max-w-xs`}
          placeholder={es.library.search}
          aria-label={es.library.search}
          value={text}
          maxLength={200}
          onChange={(e) => setText(e.target.value)}
        />
        <select
          aria-label={es.library.subject}
          className={select}
          value={subjectId}
          onChange={(e) => {
            setSubjectId(e.target.value)
            setUnitId('')
          }}
        >
          <option value="">
            {es.library.subject}: {es.common.all}
          </option>
          {subjects.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        {detail.data && detail.data.units.length > 0 && (
          <select
            aria-label={es.library.unit}
            className={select}
            value={unitId}
            onChange={(e) => setUnitId(e.target.value)}
          >
            <option value="">
              {es.library.unit}: {es.common.all}
            </option>
            {unitTree(detail.data.units).map(({ unit, depth }) => (
              <option key={unit.id} value={unit.id}>
                {'  '.repeat(depth)}
                {unit.title}
              </option>
            ))}
          </select>
        )}
        <select
          aria-label={es.library.kind}
          className={select}
          value={kind}
          onChange={(e) => setKind(e.target.value as SourceKind | '')}
        >
          <option value="">
            {es.library.kind}: {es.common.all}
          </option>
          {(Object.keys(es.kinds) as SourceKind[]).map((k) => (
            <option key={k} value={k}>
              {es.kinds[k]}
            </option>
          ))}
        </select>
        <select
          aria-label={es.library.status}
          className={select}
          value={status}
          onChange={(e) => setStatus(e.target.value as SourceStatus | '')}
        >
          <option value="">
            {es.library.status}: {es.common.all}
          </option>
          {(Object.keys(es.statuses) as SourceStatus[]).map((k) => (
            <option key={k} value={k}>
              {es.statuses[k]}
            </option>
          ))}
        </select>
      </div>

      <ErrorText>{list.error}</ErrorText>
      {list.loading && !list.data && <Loading />}
      {list.data && (
        <>
          <p className="mb-2 text-xs text-zinc-500">{es.library.total(list.data.total)}</p>
          {list.data.items.length === 0 ? (
            <p className="text-sm text-zinc-500">{es.library.empty}</p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {list.data.items.map((s) => (
                    <SourceRow
                      key={s.id}
                      source={s}
                      subject={subjectName.get(s.subject_id)}
                      onOpen={() => navigate({ name: 'source', id: s.id })}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {list.data.total > list.data.items.length && (
            <Button className="mt-4" onClick={() => setLimit((l) => l + PAGE)}>
              {es.library.more}
            </Button>
          )}
        </>
      )}
    </div>
  )
}

function SourceRow({
  source: s,
  subject,
  onOpen,
}: {
  source: Source
  subject?: string
  onOpen: () => void
}) {
  const extra =
    s.duration_ms != null
      ? formatDuration(s.duration_ms)
      : s.page_count != null
        ? `${s.page_count} pág.`
        : formatBytes(s.size_bytes)
  return (
    <tr className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900" onClick={onOpen}>
      <td className="px-4 py-2.5">
        <button type="button" className="text-left font-medium hover:underline" onClick={onOpen}>
          {s.title}
        </button>
        <div className="text-xs text-zinc-500">{subject}</div>
      </td>
      <td className="px-4 py-2.5 text-zinc-500">{es.kinds[s.kind]}</td>
      <td className="px-4 py-2.5 text-zinc-500">{extra}</td>
      <td className="px-4 py-2.5 text-zinc-500">{formatDate(s.imported_at)}</td>
      <td className="px-4 py-2.5 text-right">
        <StatusBadge status={s.status} />
      </td>
    </tr>
  )
}
