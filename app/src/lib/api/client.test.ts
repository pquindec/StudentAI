import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'
import { desktopImporter, fileName } from './files'
import type { ApiTransport } from './transport'

function client(status = 200, body: unknown = {}) {
  const request = vi.fn().mockResolvedValue({ status, body })
  return { api: new ApiClient({ request } as ApiTransport), request }
}

describe('ApiClient', () => {
  it('codifica los filtros y omite los vacíos', async () => {
    const { api, request } = client(200, { items: [], total: 0 })
    await api.listSources({ q: 'a&kind=pdf %', subject_id: '', status: 'ready', limit: 50 })
    expect(request).toHaveBeenCalledWith(
      'GET',
      '/api/v1/sources?q=a%26kind%3Dpdf%20%25&status=ready&limit=50',
      undefined,
    )
  })

  it('codifica los identificadores en la ruta', async () => {
    const { api, request } = client()
    await api.getSource('../x?y')
    expect(request).toHaveBeenCalledWith('GET', '/api/v1/sources/..%2Fx%3Fy', undefined)
  })

  it('lanza ApiError con el mensaje del backend', async () => {
    const { api } = client(409, { error: { code: 'version_conflict', message: 'Conflicto' } })
    await expect(api.saveContent('s', 't', 1)).rejects.toMatchObject({
      status: 409,
      code: 'version_conflict',
      message: 'Conflicto',
    })
  })
})

describe('desktopImporter', () => {
  it('envía destino y rutas al comando import_files', async () => {
    const invoke = vi.fn().mockResolvedValue([])
    await desktopImporter(invoke).importPaths({ subject_id: 's1', unit_ids: ['u1'] }, ['/a/b.pdf'])
    expect(invoke).toHaveBeenCalledWith('import_files', {
      request: { subject_id: 's1', unit_ids: ['u1'], session_ids: [], paths: ['/a/b.pdf'] },
    })
  })

  it('extrae el nombre del archivo', () => {
    expect(fileName('/Users/x/Clase 1.pdf')).toBe('Clase 1.pdf')
  })
})
