import type { components } from './schema'
import { type ApiTransport, type HttpMethod, toApiError } from './transport'

export type Health = components['schemas']['HealthOut']
export type SystemInfo = components['schemas']['SystemInfoOut']

/** Cliente tipado de la API. Los tipos se generan desde OpenAPI (`npm run gen:api`). */
export class ApiClient {
  private readonly transport: ApiTransport

  constructor(transport: ApiTransport) {
    this.transport = transport
  }

  private async call<T>(method: HttpMethod, path: string, body?: unknown): Promise<T> {
    const res = await this.transport.request(method, path, body)
    if (res.status < 200 || res.status >= 300) throw toApiError(res)
    return res.body as T
  }

  health(): Promise<Health> {
    return this.call('GET', '/api/v1/health')
  }

  systemInfo(): Promise<SystemInfo> {
    return this.call('GET', '/api/v1/system/info')
  }
}
