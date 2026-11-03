/**
 * Capa de transporte intercambiable (ADR-009).
 * - Escritorio: TauriTransport (invoke → Rust → Unix socket).
 * - Futuro modo web: HttpTransport (fetch con cookie de sesión).
 * Ningún componente debe llamar a `invoke` ni a `fetch` directamente.
 */

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface ApiTransport {
  request(method: HttpMethod, path: string, body?: unknown): Promise<RawResponse>
}

export interface RawResponse {
  status: number
  body: unknown
}

/** Error con un mensaje comprensible para el usuario y un código para la lógica. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string }
}

export function toApiError(res: RawResponse): ApiError {
  const err = (res.body as ErrorBody | null)?.error
  return new ApiError(res.status, err?.code ?? 'http_error', err?.message ?? `Error ${res.status}`)
}

/** Transporte para el modo escritorio. `invoke` se inyecta para poder probarlo. */
export class TauriTransport implements ApiTransport {
  private readonly invoke: (cmd: string, args: Record<string, unknown>) => Promise<unknown>

  constructor(invoke: (cmd: string, args: Record<string, unknown>) => Promise<unknown>) {
    this.invoke = invoke
  }

  async request(method: HttpMethod, path: string, body?: unknown): Promise<RawResponse> {
    try {
      return (await this.invoke('api_request', {
        request: { method, path, body: body ?? null },
      })) as RawResponse
    } catch (e) {
      // Los errores del lado Rust llegan como texto ya redactado en español.
      throw new ApiError(0, 'transport_error', typeof e === 'string' ? e : String(e))
    }
  }
}

/** Transporte para el futuro modo web. No se usa en escritorio. */
export class HttpTransport implements ApiTransport {
  private readonly baseUrl: string
  private readonly fetchFn: typeof fetch

  constructor(baseUrl: string, fetchFn: typeof fetch = fetch) {
    this.baseUrl = baseUrl
    this.fetchFn = fetchFn
  }

  async request(method: HttpMethod, path: string, body?: unknown): Promise<RawResponse> {
    let res: Response
    try {
      res = await this.fetchFn(`${this.baseUrl}${path}`, {
        method,
        credentials: 'same-origin',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch {
      throw new ApiError(0, 'transport_error', 'No se pudo conectar con el servidor')
    }
    const text = await res.text()
    return { status: res.status, body: text ? (JSON.parse(text) as unknown) : null }
  }
}
