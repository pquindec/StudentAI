import { es } from '../i18n/es'
import type { BackendStatus } from '../lib/backendStatus'
import { JobsPanel } from './JobsPanel'
import { StatusDot } from './StatusDot'

export type Section = keyof typeof es.nav

const GROUPS: Section[][] = [
  ['dashboard', 'subjects'],
  ['recordings', 'import', 'library'],
  ['notes', 'summaries', 'exams', 'flashcards', 'assistant'],
  ['stats', 'settings'],
]

interface Props {
  current: Section
  onSelect: (s: Section) => void
  status: BackendStatus
}

export function Sidebar({ current, onSelect, status }: Props) {
  return (
    <nav
      aria-label="Navegación principal"
      className="flex w-60 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900"
    >
      <div className="px-5 pt-6 pb-4 text-[15px] font-semibold tracking-tight">{es.appName}</div>
      <div className="flex-1 space-y-4 overflow-y-auto px-3">
        {GROUPS.map((group, i) => (
          <ul key={i} className="space-y-0.5">
            {group.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  onClick={() => onSelect(s)}
                  aria-current={current === s ? 'page' : undefined}
                  className={`w-full rounded-md px-3 py-1.5 text-left text-sm transition-colors ${
                    current === s
                      ? 'bg-accent-100 font-medium text-accent-700 dark:bg-accent-700/30 dark:text-accent-100'
                      : 'text-zinc-700 hover:bg-zinc-200/70 dark:text-zinc-300 dark:hover:bg-zinc-800'
                  }`}
                >
                  {es.nav[s]}
                </button>
              </li>
            ))}
          </ul>
        ))}
      </div>
      <JobsPanel enabled={status.state === 'ready'} />
      <div className="flex items-center gap-2 border-t border-zinc-200 px-5 py-3 text-xs text-zinc-500 dark:border-zinc-800">
        <StatusDot status={status} />
        <span>{es.backend[status.state]}</span>
      </div>
    </nav>
  )
}
