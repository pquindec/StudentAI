import { useEffect, useState } from 'react'
import { DocStatusBadge } from '../components/Documents'
import { Button, Card, ConfirmButton, ErrorText, Loading, PageHeader } from '../components/ui'
import { es } from '../i18n/es'
import { api, type DocCitation } from '../lib/api'
import { formatDate, formatDuration } from '../lib/format'
import { isBusy } from '../lib/documents'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'

function Refs({
  refs,
  known,
  selected,
  onSelect,
}: {
  refs: number[]
  known: Map<number, DocCitation>
  selected: number | null
  onSelect: (n: number) => void
}) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-0.5 align-baseline">
      {refs.map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onSelect(n)}
          aria-label={`${es.docs.citation} ${n}`}
          aria-pressed={selected === n}
          className={`rounded px-1 text-[11px] font-medium tabular-nums ${
            !known.has(n)
              ? 'bg-zinc-100 text-zinc-400 line-through dark:bg-zinc-800'
              : selected === n
                ? 'bg-accent-600 text-white'
                : 'bg-accent-100 text-accent-700 hover:bg-accent-200 dark:bg-accent-700/30 dark:text-accent-100'
          }`}
        >
          {n}
        </button>
      ))}
    </span>
  )
}

function CitationPanel({ ref_, cite }: { ref_: number; cite: DocCitation | undefined }) {
  const navigate = useNavigate()
  if (!cite) {
    return (
      <Card>
        <p className="text-sm text-zinc-500">
          [{ref_}] {es.docs.deletedSource}
        </p>
      </Card>
    )
  }
  const where =
    cite.start_ms != null
      ? formatDuration(cite.start_ms)
      : cite.page != null
        ? es.docs.page(cite.page)
        : null
  return (
    <Card className="space-y-3">
      <div className="text-xs text-zinc-500">
        [{ref_}] {cite.source_title}
        {where ? ` · ${where}` : ''}
      </div>
      <blockquote className="border-l-2 border-accent-500 pl-3 text-sm whitespace-pre-wrap">
        {cite.text}
      </blockquote>
      <Button
        onClick={() =>
          navigate({ name: 'source', id: cite.source_id, at: cite.start_ms ?? undefined })
        }
      >
        {es.docs.openSource}
      </Button>
    </Card>
  )
}

export function DocumentView({ id }: { id: string }) {
  const navigate = useNavigate()
  const q = useQuery(() => api.getDocument(id), [id])
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const d = q.data
  const busy = d ? isBusy(d) : false

  const { reload } = q
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => reload(), 1500)
    return () => window.clearInterval(t)
  }, [busy, reload])

  if (!d) {
    return (
      <div className="mx-auto max-w-5xl px-10 py-10">
        {q.error ? <ErrorText>{q.error}</ErrorText> : <Loading />}
      </div>
    )
  }

  const known = new Map(d.citations.map((c) => [c.ref, c]))
  const section = d.kind === 'notes' ? 'notes' : 'summaries'
  const refsProps = { known, selected, onSelect: setSelected }

  const retry = async () => {
    setError(null)
    try {
      await api.retryDocument(d.id)
      reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-10 py-10">
      <button
        type="button"
        className="mb-3 text-sm text-zinc-500 hover:underline"
        onClick={() => navigate({ name: section })}
      >
        ← {es.nav[section]}
      </button>
      <PageHeader
        title={d.title}
        subtitle={`${es.docs.kind[d.kind]} · ${es.docs.details[d.detail]} · ${formatDate(d.created_at)}`}
        actions={
          <ConfirmButton
            label={es.common.delete}
            title={d.title}
            onConfirm={async () => {
              await api.deleteDocument(d.id)
              navigate({ name: section })
            }}
          />
        }
      />
      <ErrorText>{error}</ErrorText>
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-6">
          {busy && (
            <Card className="space-y-2">
              <div className="flex items-center gap-3">
                <DocStatusBadge doc={d} />
                <span className="text-sm text-zinc-500">{d.message}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
                <div
                  className="h-full bg-accent-600 transition-[width]"
                  style={{ width: `${Math.round(d.progress * 100)}%` }}
                />
              </div>
              <p className="text-xs text-zinc-500">{es.docs.queuedHint}</p>
            </Card>
          )}
          {(d.status === 'failed' || d.status === 'cancelled') && (
            <Card className="space-y-3">
              <DocStatusBadge doc={d} />
              <ErrorText>{d.error_message}</ErrorText>
              <Button onClick={() => void retry()}>{es.common.retry}</Button>
            </Card>
          )}
          {d.status === 'ready' && (
            <Card className="space-y-6">
              {d.sections.map((s, i) => (
                <section key={i}>
                  <h2 className="mb-2 font-semibold">{s.title}</h2>
                  {s.prose ? (
                    <p className="text-[15px] leading-relaxed">
                      {s.points.map((p, j) => (
                        <span key={j}>
                          {p.text}
                          <Refs refs={p.refs} {...refsProps} />{' '}
                        </span>
                      ))}
                    </p>
                  ) : (
                    <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed">
                      {s.points.map((p, j) => (
                        <li key={j}>
                          {p.text}
                          <Refs refs={p.refs} {...refsProps} />
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </Card>
          )}
          {d.contradictions.length > 0 && (
            <Card className="space-y-4 border-amber-300 dark:border-amber-800">
              <div>
                <h2 className="font-semibold">{es.docs.contradictions}</h2>
                <p className="text-xs text-zinc-500">{es.docs.contradictionsHint}</p>
              </div>
              {d.contradictions.map((c, i) => (
                <div key={i}>
                  <h3 className="mb-2 text-sm font-medium">{c.topic}</h3>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {c.claims.map((cl, j) => (
                      <div
                        key={j}
                        className="rounded-md bg-amber-50 p-3 text-sm dark:bg-amber-900/20"
                      >
                        <div className="mb-1 text-xs text-zinc-500">
                          {cl.refs
                            .map((n) => known.get(n)?.source_title ?? es.docs.deletedSource)
                            .filter((t, k, all) => all.indexOf(t) === k)
                            .join(', ')}
                        </div>
                        {cl.text}
                        <Refs refs={cl.refs} {...refsProps} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </Card>
          )}
        </div>
        <aside className="space-y-4 self-start lg:sticky lg:top-4">
          {selected != null && <CitationPanel ref_={selected} cite={known.get(selected)} />}
          <Card className="space-y-2 text-xs text-zinc-500">
            <div>{es.docs.from}</div>
            <ul className="space-y-1">
              {d.sources.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className="text-left text-sm text-zinc-700 hover:underline dark:text-zinc-300"
                    onClick={() => navigate({ name: 'source', id: s.id })}
                  >
                    {s.title}
                  </button>
                </li>
              ))}
            </ul>
            {d.model && <div>{es.docs.model(d.model)}</div>}
            {d.status === 'ready' && (
              <>
                <div>{es.docs.verified(d.citations.length)}</div>
                {d.stats.invented_cites > 0 && (
                  <div>{es.docs.discarded(d.stats.invented_cites)}</div>
                )}
                {d.stats.fallback && <div>{es.docs.fallback}</div>}
              </>
            )}
          </Card>
        </aside>
      </div>
    </div>
  )
}
