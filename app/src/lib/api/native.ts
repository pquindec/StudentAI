/**
 * Funciones nativas del escritorio (Rust): grabación, guardar exportaciones y audio local.
 * En el futuro modo web no existen (la grabación usaría MediaRecorder; ADR-009).
 */

export interface InputDevice {
  id: string
  name: string
  is_default: boolean
}

export type RecordingState = 'idle' | 'recording' | 'paused'

export interface RecordingStatus {
  state: RecordingState
  id: string | null
  title: string | null
  subject_id: string | null
  elapsed_ms: number
  level: number
  heard: boolean
  device: string | null
  error: string | null
}

export interface RecordingTarget {
  subject_id: string
  title: string
  unit_ids?: string[]
  session_ids?: string[]
}

export interface RecordingImport {
  recording_id: string
  status: number
  body: unknown
  warning: string | null
}

export interface Recoverable {
  id: string
  title: string
  subject_id: string
  started_at_ms: number
  duration_ms: number
}

export interface Native {
  devices(): Promise<InputDevice[]>
  status(): Promise<RecordingStatus>
  start(target: RecordingTarget, deviceId?: string): Promise<RecordingStatus>
  pause(resume: boolean): Promise<RecordingStatus>
  stop(): Promise<RecordingImport>
  recoverable(): Promise<Recoverable[]>
  recover(id: string): Promise<RecordingImport>
  discard(id: string): Promise<void>
  onStatus(cb: (s: RecordingStatus) => void): Promise<() => void>
  /** Guarda texto con el diálogo nativo. Devuelve la ruta o null si se canceló. */
  saveText(defaultName: string, content: string): Promise<string | null>
  /** URL reproducible para un archivo local permitido (solo audios normalizados). */
  mediaUrl(path: string): Promise<string>
}

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

export function desktopNative(invoke: Invoke): Native {
  return {
    devices: async () => (await invoke('list_input_devices')) as InputDevice[],
    status: async () => (await invoke('recording_status')) as RecordingStatus,
    start: async (target, deviceId) =>
      (await invoke('start_recording', {
        request: { device_id: deviceId ?? null, target },
      })) as RecordingStatus,
    pause: async (resume) => (await invoke('pause_recording', { resume })) as RecordingStatus,
    stop: async () => (await invoke('stop_recording')) as RecordingImport,
    recoverable: async () => (await invoke('list_recoverable_recordings')) as Recoverable[],
    recover: async (id) => (await invoke('recover_recording', { id })) as RecordingImport,
    discard: async (id) => {
      await invoke('discard_recording', { id })
    },
    onStatus: async (cb) => {
      const { listen } = await import('@tauri-apps/api/event')
      return listen<RecordingStatus>('recording://status', (e) => cb(e.payload))
    },
    saveText: async (defaultName, content) =>
      (await invoke('save_text_file', { defaultName, content })) as string | null,
    mediaUrl: async (path) => {
      const { convertFileSrc } = await import('@tauri-apps/api/core')
      return convertFileSrc(path)
    },
  }
}

/** Los errores de los comandos Rust llegan como texto ya redactado en español. */
export function nativeError(e: unknown): string {
  return typeof e === 'string' ? e : e instanceof Error ? e.message : String(e)
}
