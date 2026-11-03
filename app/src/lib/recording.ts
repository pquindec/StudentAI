import { createContext, useContext } from 'react'
import type { RecordingImport, RecordingStatus, RecordingTarget } from './api'

export interface RecordingApi {
  status: RecordingStatus
  busy: boolean
  error: string | null
  lastResult: RecordingImport | null
  start(target: RecordingTarget, deviceId?: string): Promise<boolean>
  pause(resume: boolean): Promise<void>
  stop(): Promise<void>
  dismissResult(): void
}

export const IDLE: RecordingStatus = {
  state: 'idle',
  id: null,
  title: null,
  subject_id: null,
  elapsed_ms: 0,
  level: 0,
  heard: false,
  device: null,
  error: null,
}

export const RecordingContext = createContext<RecordingApi | null>(null)

export function useRecording(): RecordingApi {
  const ctx = useContext(RecordingContext)
  if (!ctx) throw new Error('RecordingContext no disponible')
  return ctx
}

/** Id de la fuente creada al importar una grabación (si la importación fue bien). */
export function importedSourceId(r: RecordingImport | null): string | null {
  if (!r || r.status !== 201) return null
  const id = (r.body as { id?: unknown } | null)?.id
  return typeof id === 'string' ? id : null
}
