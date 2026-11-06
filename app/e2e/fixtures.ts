import { type ChildProcess, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { request as httpRequest } from 'node:http'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test as base, expect, type Page } from '@playwright/test'

const BACKEND = resolve(import.meta.dirname, '../../backend')

export interface Backend {
  /** Llama a la API directamente (para preparar datos sin pasar por la interfaz). */
  api: <T = unknown>(method: string, path: string, body?: unknown) => Promise<T>
  dataDir: string
}

function call(socket: string, token: string, method: string, path: string, body?: Buffer) {
  return new Promise<{ status: number; headers: Record<string, string>; body: Buffer }>(
    (ok, fail) => {
      const req = httpRequest(
        {
          socketPath: socket,
          path,
          method,
          headers: {
            authorization: `Bearer ${token}`,
            'content-type': 'application/json',
            'content-length': body?.length ?? 0,
          },
        },
        (res) => {
          const chunks: Buffer[] = []
          res.on('data', (c: Buffer) => chunks.push(c))
          res.on('end', () =>
            ok({
              status: res.statusCode ?? 500,
              headers: { 'content-type': String(res.headers['content-type'] ?? '') },
              body: Buffer.concat(chunks),
            }),
          )
        },
      )
      req.on('error', fail)
      if (body?.length) req.write(body)
      req.end()
    },
  )
}

async function start(): Promise<{
  proc: ChildProcess
  dir: string
  socket: string
  token: string
  log: () => string
}> {
  const dir = mkdtempSync(join(tmpdir(), 'sa-e2e-'))
  const socket = join(dir, 'b.sock')
  const token = randomBytes(32).toString('hex')
  const proc = spawn(
    'uv',
    [
      'run',
      '--frozen',
      'python',
      '-m',
      'tests.e2e_server',
      '--data-dir',
      join(dir, 'data'),
      '--socket',
      socket,
    ],
    { cwd: BACKEND, stdio: ['pipe', 'ignore', 'pipe'] },
  )
  let log = ''
  proc.stderr?.on('data', (d: Buffer) => (log += d.toString()))
  proc.stdin?.write(token + '\n') // el token, como lo envía Tauri; stdin queda abierto
  for (let i = 0; i < 200; i++) {
    if (existsSync(socket)) {
      try {
        const r = await call(socket, token, 'GET', '/api/v1/health')
        if (r.status === 200) return { proc, dir, socket, token, log: () => log }
      } catch {
        // aún arrancando
      }
    }
    await new Promise((r) => setTimeout(r, 100))
  }
  proc.kill()
  throw new Error('El backend de pruebas no arrancó:\n' + log)
}

/** Reenvía /api/v1/* del navegador al socket del backend, con el token (como el proxy de Rust). */
async function wire(page: Page, socket: string, token: string) {
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const res = await call(
      socket,
      token,
      req.method(),
      url.pathname + url.search,
      req.postDataBuffer() ?? undefined,
    )
    await route.fulfill({ status: res.status, headers: res.headers, body: res.body })
  })
}

export const test = base.extend<{ backend: Backend }>({
  backend: async ({ page }, provide, testInfo) => {
    const b = await start()
    await wire(page, b.socket, b.token)
    const api = async <T>(method: string, path: string, body?: unknown): Promise<T> => {
      const res = await call(
        b.socket,
        b.token,
        method,
        '/api/v1' + path,
        body === undefined ? undefined : Buffer.from(JSON.stringify(body)),
      )
      if (res.status >= 400)
        throw new Error(`${method} ${path} → ${res.status} ${res.body.toString()}`)
      return (res.body.length ? JSON.parse(res.body.toString()) : undefined) as T
    }
    await provide({ api, dataDir: join(b.dir, 'data') })
    if (testInfo.status !== testInfo.expectedStatus)
      await testInfo.attach('backend.log', { body: b.log(), contentType: 'text/plain' })
    await page.unrouteAll({ behavior: 'ignoreErrors' }) // sin peticiones a medias al cerrar
    b.proc.stdin?.end() // EOF: el backend sale solo
    await new Promise((r) => b.proc.once('exit', r))
    rmSync(b.dir, { recursive: true, force: true })
  },
})

export { expect }

export const TEXT = Array.from(
  { length: 12 },
  (_, i) =>
    `Párrafo ${i}: la arquitectura número ${i} define componentes, conectores y restricciones` +
    ` que guían la evolución del sistema durante años de mantenimiento continuado ${i}.`,
).join('\n\n')

/** Una asignatura con una fuente de texto ya indexada (lista para el asistente). */
export async function seed(backend: Backend): Promise<string> {
  const s = await backend.api<{ id: string }>('POST', '/subjects', { name: 'Arquitectura' })
  const src = await backend.api<{ id: string }>('POST', '/sources/text', {
    subject_id: s.id,
    title: 'Tema 1',
    text: TEXT,
  })
  await expect
    .poll(
      async () => (await backend.api<{ status: string }>('GET', `/sources/${src.id}/index`)).status,
    )
    .toBe('ready')
  return s.id
}
