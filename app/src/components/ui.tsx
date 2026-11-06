import { type ReactNode, useEffect, useRef, useState } from 'react'
import { es } from '../i18n/es'
import type { SourceStatus } from '../lib/api'
import { errorMessage } from '../lib/useQuery'

export const inputClass =
  'w-full rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-500/30 dark:border-zinc-700 dark:bg-zinc-900'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent-600 text-white hover:bg-accent-700 disabled:bg-accent-600/50',
  secondary:
    'border border-zinc-300 bg-white hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800',
  danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/50',
  ghost: 'text-zinc-600 hover:bg-zinc-200/70 dark:text-zinc-300 dark:hover:bg-zinc-800',
}

export function Button({
  variant = 'secondary',
  className = '',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${VARIANT[variant]} ${className}`}
      {...props}
    />
  )
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{label}</span>
      {children}
      {hint && <span className="block text-xs text-zinc-500">{hint}</span>}
    </label>
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <p role="alert" className="text-sm text-red-600 dark:text-red-400">
      {children}
    </p>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  )
}

/** Modal accesible con `<dialog>` nativo (foco atrapado y Escape para cerrar). */
export function Modal({
  open,
  title,
  onClose,
  children,
  wide = false,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="modal-title"
      className={`m-auto w-full ${wide ? 'max-w-2xl' : 'max-w-md'} rounded-xl border border-zinc-200 bg-white p-0 text-zinc-900 shadow-xl backdrop:bg-black/40 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100`}
    >
      {open && (
        <div className="p-5">
          <h2 id="modal-title" className="mb-4 text-base font-semibold">
            {title}
          </h2>
          {children}
        </div>
      )}
    </dialog>
  )
}

/** Botón que pide confirmación antes de una acción destructiva. */
export function ConfirmButton({
  label,
  title,
  body,
  onConfirm,
  variant = 'ghost',
}: {
  label: string
  title: string
  body?: string
  onConfirm: () => Promise<unknown>
  variant?: Variant
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirm = async () => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
      setOpen(false)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <Modal open={open} title={title} onClose={() => setOpen(false)}>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {body ?? es.common.confirmDelete}
        </p>
        <div className="mt-3">
          <ErrorText>{error}</ErrorText>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => setOpen(false)}>{es.common.cancel}</Button>
          <Button variant="danger" disabled={busy} onClick={() => void confirm()}>
            {label}
          </Button>
        </div>
      </Modal>
    </>
  )
}

const STATUS_STYLE: Record<SourceStatus, string> = {
  pending: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  processing: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  ready: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  cancelled: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
}

export function StatusBadge({ status }: { status: SourceStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}>
      {es.statuses[status]}
    </span>
  )
}

export function Loading() {
  return <p className="text-sm text-zinc-500">{es.common.loading}</p>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-zinc-200 p-5 dark:border-zinc-800 ${className}`}>
      {children}
    </section>
  )
}
