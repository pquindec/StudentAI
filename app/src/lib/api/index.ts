import { invoke } from '@tauri-apps/api/core'
import { ApiClient } from './client'
import { desktopImporter, type FileImporter } from './files'
import { HttpTransport, TauriTransport } from './transport'

export const isDesktop = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

/** Instancia única del cliente: escritorio vía Tauri; en navegador, HTTP al mismo origen. */
export const api = new ApiClient(
  isDesktop ? new TauriTransport((cmd, args) => invoke(cmd, args)) : new HttpTransport(''),
)

/** Importación desde el disco: solo existe en escritorio (en web llegará la subida HTTP). */
export const files: FileImporter | null = isDesktop
  ? desktopImporter((cmd, args) => invoke(cmd, args))
  : null

export { ApiError } from './transport'
export { fileName } from './files'
export type { DropState, ImportResult } from './files'
export type * from './client'
