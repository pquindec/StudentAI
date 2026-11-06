import { useState } from 'react'
import { es } from '../i18n/es'

export interface Bar {
  key: string
  label: string // eje X (corto)
  value: number
  tooltip: string
  muted?: boolean
}

/** Barras de una serie: marcas finas con extremo redondeado, eje recesivo, tooltip al pasar el
 * ratón (o con el teclado) y vista de tabla para quien no pueda leer el gráfico. */
export function BarChart({
  bars,
  height = 120,
  unit,
  everyLabel = 1,
  tableHeaders,
}: {
  bars: Bar[]
  height?: number
  unit: (v: number) => string
  everyLabel?: number
  tableHeaders: [string, string]
}) {
  const [hover, setHover] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const max = Math.max(1, ...bars.map((b) => b.value))
  const active = hover != null ? bars[hover] : null
  return (
    <div className="space-y-2">
      <div className="flex h-5 items-center justify-between text-xs text-zinc-500">
        <span aria-live="polite" className="text-zinc-700 dark:text-zinc-300">
          {active ? active.tooltip : ''}
        </span>
        <button type="button" className="hover:underline" onClick={() => setTable((t) => !t)}>
          {table ? es.common.back : es.stats.table}
        </button>
      </div>
      {table ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-zinc-500">
              <th className="font-medium">{tableHeaders[0]}</th>
              <th className="text-right font-medium">{tableHeaders[1]}</th>
            </tr>
          </thead>
          <tbody>
            {bars.map((b) => (
              <tr key={b.key} className="border-t border-zinc-100 dark:border-zinc-800">
                <td className="py-1">{b.tooltip.split(':')[0]}</td>
                <td className="py-1 text-right tabular-nums">{unit(b.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="flex gap-2">
          <div
            className="flex flex-col justify-between text-right text-[10px] text-zinc-400 tabular-nums"
            style={{ height }}
          >
            <span>{unit(max)}</span>
            <span>0</span>
          </div>
          <div className="min-w-0 flex-1">
            <div
              className="flex items-end gap-[2px] border-b border-zinc-200 dark:border-zinc-800"
              style={{ height }}
              onMouseLeave={() => setHover(null)}
            >
              {bars.map((b, i) => (
                <button
                  key={b.key}
                  type="button"
                  aria-label={b.tooltip}
                  className="flex h-full min-w-0 flex-1 items-end focus-visible:outline-1"
                  onMouseEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                >
                  <span
                    className="block w-full rounded-t-[4px]"
                    style={{
                      height: b.value ? `max(2px, ${(b.value / max) * 100}%)` : 0,
                      background: b.muted ? 'var(--bar-muted)' : 'var(--bar)',
                      opacity: hover == null || hover === i ? 1 : 0.55,
                    }}
                  />
                </button>
              ))}
            </div>
            <div className="mt-1 flex gap-[2px] text-[10px] text-zinc-400">
              {bars.map((b, i) => (
                <span key={b.key} className="min-w-0 flex-1 truncate text-center">
                  {i % everyLabel === 0 || i === bars.length - 1 ? b.label : ''}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
