import { Button, Card } from './ui'
import { es } from '../i18n/es'
import type { DocCitation } from '../lib/api'
import { formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'

/** Referencias numeradas [1] [2]… que abren la cita (apuntes, resúmenes y asistente). */
export function Refs({
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

export function CitationPanel({ ref_, cite }: { ref_: number; cite: DocCitation | undefined }) {
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
