import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { ApiError, HttpTransport, TauriTransport } from './transport'

describe('TauriTransport', () => {
  it('envía la petición al comando api_request', async () => {
    const invoke = vi.fn().mockResolvedValue({ status: 200, body: { status: 'ok' } })
    const res = await new TauriTransport(invoke).request('GET', '/api/v1/health')
    expect(invoke).toHaveBeenCalledWith('api_request', {
      request: { method: 'GET', path: '/api/v1/health', body: null },
    })
    expect(res.status).toBe(200)
  })

  it('convierte los errores de Rust en ApiError legible', async () => {
    const invoke = vi.fn().mockRejectedValue('El servicio local aún no está listo')
    await expect(new TauriTransport(invoke).request('GET', '/api/v1/x')).rejects.toMatchObject({
      code: 'transport_error',
      message: 'El servicio local aún no está listo',
    })
  })
})

describe('HttpTransport', () => {
  it('serializa el cuerpo JSON', async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 201 }))
    const res = await new HttpTransport('https://srv', fetchFn).request('POST', '/api/v1/s', {
      a: 1,
    })
    expect(fetchFn).toHaveBeenCalledWith(
      'https://srv/api/v1/s',
      expect.objectContaining({ method: 'POST', body: '{"a":1}' }),
    )
    expect(res).toEqual({ status: 201, body: { ok: true } })
  })

  it('llama a fetch sobre globalThis, como exigen los navegadores', async () => {
    const real = globalThis.fetch
    globalThis.fetch = function (this: unknown) {
      if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation')
      return Promise.resolve(new Response('null', { status: 200 }))
    } as typeof fetch
    try {
      await expect(new HttpTransport('').request('GET', '/api/v1/health')).resolves.toEqual({
        status: 200,
        body: null,
      })
    } finally {
      globalThis.fetch = real
    }
  })
})

describe('ApiClient', () => {
  it('lanza ApiError con el mensaje del backend en respuestas no 2xx', async () => {
    const transport = {
      request: vi.fn().mockResolvedValue({
        status: 401,
        body: { error: { code: 'unauthorized', message: 'No autorizado' } },
      }),
    }
    const err = await new ApiClient(transport).health().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 401, code: 'unauthorized', message: 'No autorizado' })
  })
})
