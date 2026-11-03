import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { useEffect, useState } from 'react'
import { isDesktop } from './api'

export type BackendStatus =
  | { state: 'starting' }
  | { state: 'ready' }
  | { state: 'failed'; message: string }
  | { state: 'stopped' }

/** Estado del servicio local, actualizado por eventos del proceso Rust. */
export function useBackendStatus(): BackendStatus {
  // En el futuro modo web no hay proceso local que supervisar.
  const [status, setStatus] = useState<BackendStatus>(
    isDesktop ? { state: 'starting' } : { state: 'ready' },
  )

  useEffect(() => {
    if (!isDesktop) return
    let active = true
    const unlisten = listen<BackendStatus>('backend://status', (e) => {
      if (active) setStatus(e.payload)
    })
    invoke<BackendStatus>('backend_status')
      .then((s) => active && setStatus(s))
      .catch(() => active && setStatus({ state: 'failed', message: 'Estado no disponible' }))
    return () => {
      active = false
      void unlisten.then((fn) => fn())
    }
  }, [])

  return status
}
