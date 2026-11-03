import { useCallback, useEffect, useRef, useState } from 'react'
import { es } from '../i18n/es'
import { ApiError } from './api'

export interface Query<T> {
  data: T | undefined
  error: string | null
  loading: boolean
  reload: () => void
}

export function errorMessage(e: unknown): string {
  return e instanceof ApiError ? e.message : es.common.unexpected
}

interface State<T> {
  key: string | null
  data: T | undefined
  error: string | null
}

/**
 * Carga datos asíncronos y descarta respuestas obsoletas si cambian las dependencias.
 * Hook mínimo propio en lugar de una librería: pocas consultas y sin caché compartida.
 * Mientras recarga conserva los datos anteriores (no hay parpadeos).
 */
export function useQuery<T>(fn: () => Promise<T>, deps: readonly unknown[]): Query<T> {
  const [state, setState] = useState<State<T>>({ key: null, data: undefined, error: null })
  const [nonce, setNonce] = useState(0)
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  })
  const key = `${JSON.stringify(deps)}#${nonce}`

  useEffect(() => {
    const ac = new AbortController()
    fnRef.current().then(
      (data) => {
        if (!ac.signal.aborted) setState({ key, data, error: null })
      },
      (e: unknown) => {
        if (!ac.signal.aborted) setState((s) => ({ ...s, key, error: errorMessage(e) }))
      },
    )
    return () => ac.abort()
  }, [key])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data: state.data, error: state.error, loading: state.key !== key, reload }
}
