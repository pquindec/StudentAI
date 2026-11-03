import { invoke } from '@tauri-apps/api/core'
import { ApiClient } from './client'
import { HttpTransport, TauriTransport } from './transport'

export const isDesktop = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

/** Instancia única del cliente: escritorio vía Tauri; en navegador, HTTP al mismo origen. */
export const api = new ApiClient(
  isDesktop ? new TauriTransport((cmd, args) => invoke(cmd, args)) : new HttpTransport(''),
)

export { ApiError } from './transport'
export type { Health, SystemInfo } from './client'
