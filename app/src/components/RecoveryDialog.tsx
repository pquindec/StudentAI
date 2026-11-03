import { useEffect, useState } from 'react'
import { es } from '../i18n/es'
import { native, nativeError, type Recoverable } from '../lib/api'
import { formatDate, formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { importedSourceId } from '../lib/recording'
import { Button, ErrorText, Modal } from './ui'

/** Al abrir la app: ofrece recuperar grabaciones que quedaron a medias por un cierre. */
export function RecoveryDialog({ enabled }: { enabled: boolean }) {
  const [items, setItems] = useState<Recoverable[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!enabled || !native) return
    const ac = new AbortController()
    void native.recoverable().then((list) => {
      if (ac.signal.aborted) return
      setItems(list)
      setOpen(list.length > 0)
    })
    return () => ac.abort()
  }, [enabled])

  const remove = (id: string) => {
    const rest = items.filter((x) => x.id !== id)
    setItems(rest)
    if (!rest.length) setOpen(false)
  }

  const recover = async (id: string) => {
    if (!native) return
    setBusy(id)
    setError(null)
    try {
      const r = await native.recover(id)
      const sid = importedSourceId(r)
      if (!sid) {
        const msg = (r.body as { error?: { message?: string } } | null)?.error?.message
        setError(msg ?? es.common.unexpected)
        return
      }
      remove(id)
      navigate({ name: 'source', id: sid })
    } catch (e) {
      setError(nativeError(e))
    } finally {
      setBusy(null)
    }
  }

  const discard = async (id: string) => {
    if (!native) return
    try {
      await native.discard(id)
      setConfirmDiscard(null)
      remove(id)
    } catch (e) {
      setError(nativeError(e))
    }
  }

  return (
    <Modal open={open} title={es.recording.recoverTitle} onClose={() => setOpen(false)}>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{es.recording.recoverBody}</p>
      <ul className="mt-4 divide-y divide-zinc-100 dark:divide-zinc-800">
        {items.map((r) => (
          <li key={r.id} className="py-3 text-sm">
            <div className="font-medium">{r.title}</div>
            <div className="text-xs text-zinc-500">
              {formatDate(new Date(r.started_at_ms).toISOString())} ·{' '}
              {formatDuration(r.duration_ms)}
            </div>
            {confirmDiscard === r.id ? (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-xs">{es.recording.discardConfirm}</span>
                <Button variant="danger" onClick={() => void discard(r.id)}>
                  {es.recording.discard}
                </Button>
                <Button onClick={() => setConfirmDiscard(null)}>{es.common.cancel}</Button>
              </div>
            ) : (
              <div className="mt-2 flex gap-2">
                <Button
                  variant="primary"
                  disabled={busy !== null}
                  onClick={() => void recover(r.id)}
                >
                  {busy === r.id ? es.recording.stopping : es.recording.recover}
                </Button>
                <Button disabled={busy !== null} onClick={() => setConfirmDiscard(r.id)}>
                  {es.recording.discard}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-3">
        <ErrorText>{error}</ErrorText>
      </div>
      <div className="mt-4 flex justify-end">
        <Button variant="ghost" onClick={() => setOpen(false)}>
          {es.recording.later}
        </Button>
      </div>
    </Modal>
  )
}
