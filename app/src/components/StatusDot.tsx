import type { BackendStatus } from '../lib/backendStatus'

const COLOR: Record<BackendStatus['state'], string> = {
  starting: 'bg-amber-400 animate-pulse',
  ready: 'bg-emerald-500',
  failed: 'bg-red-500',
  stopped: 'bg-zinc-400',
}

export function StatusDot({ status }: { status: BackendStatus }) {
  return <span aria-hidden className={`inline-block size-2 rounded-full ${COLOR[status.state]}`} />
}
