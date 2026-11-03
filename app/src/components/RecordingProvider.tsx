import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { native, nativeError, type RecordingImport, type RecordingStatus } from '../lib/api'
import { IDLE, RecordingContext, type RecordingApi } from '../lib/recording'

/** Estado de la grabación compartido por toda la app (barra superior y página Grabaciones). */
export function RecordingProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<RecordingStatus>(IDLE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<RecordingImport | null>(null)

  useEffect(() => {
    if (!native) return
    const ac = new AbortController()
    void native.status().then((s) => {
      if (!ac.signal.aborted) setStatus(s)
    })
    void native
      .onStatus((s) => setStatus(s))
      .then((unlisten) => {
        if (ac.signal.aborted) unlisten()
        else ac.signal.addEventListener('abort', unlisten)
      })
    return () => ac.abort()
  }, [])

  const start = useCallback<RecordingApi['start']>(async (target, deviceId) => {
    if (!native) return false
    setBusy(true)
    setError(null)
    setLastResult(null)
    try {
      setStatus(await native.start(target, deviceId))
      return true
    } catch (e) {
      setError(nativeError(e))
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  const pause = useCallback(async (resume: boolean) => {
    if (!native) return
    try {
      setStatus(await native.pause(resume))
    } catch (e) {
      setError(nativeError(e))
    }
  }, [])

  const stop = useCallback(async () => {
    if (!native) return
    setBusy(true)
    setError(null)
    try {
      setLastResult(await native.stop())
    } catch (e) {
      setError(nativeError(e))
    } finally {
      setStatus(IDLE)
      setBusy(false)
    }
  }, [])

  const value = useMemo<RecordingApi>(
    () => ({
      status,
      busy,
      error,
      lastResult,
      start,
      pause,
      stop,
      dismissResult: () => setLastResult(null),
    }),
    [status, busy, error, lastResult, start, pause, stop],
  )
  return <RecordingContext.Provider value={value}>{children}</RecordingContext.Provider>
}
