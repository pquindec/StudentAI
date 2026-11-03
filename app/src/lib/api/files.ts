/**
 * Importación de archivos del disco (solo escritorio).
 *
 * La UI nunca envía rutas arbitrarias al backend: el núcleo Rust solo importa rutas que el
 * usuario eligió en el selector nativo o soltó sobre la ventana (ver `src-tauri/src/grants.rs`).
 */

export interface ImportTarget {
  subject_id: string
  unit_ids?: string[]
  session_ids?: string[]
}

export interface ImportResult {
  path: string
  status: number
  body: unknown
}

export type DropState = 'enter' | 'leave' | { paths: string[] }

export interface FileImporter {
  pick(): Promise<string[]>
  importPaths(target: ImportTarget, paths: string[]): Promise<ImportResult[]>
  /** Escucha archivos soltados sobre la ventana. Devuelve la función para dejar de escuchar. */
  onDrop(cb: (state: DropState) => void): Promise<() => void>
}

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

export function desktopImporter(invoke: Invoke): FileImporter {
  return {
    pick: async () => (await invoke('pick_files')) as string[],
    importPaths: async (target, paths) =>
      (await invoke('import_files', {
        request: {
          subject_id: target.subject_id,
          unit_ids: target.unit_ids ?? [],
          session_ids: target.session_ids ?? [],
          paths,
        },
      })) as ImportResult[],
    onDrop: async (cb) => {
      const { getCurrentWebview } = await import('@tauri-apps/api/webview')
      return getCurrentWebview().onDragDropEvent((e) => {
        const p = e.payload
        if (p.type === 'enter' || p.type === 'over') cb('enter')
        else if (p.type === 'leave') cb('leave')
        else cb({ paths: p.paths })
      })
    },
  }
}

export function fileName(path: string): string {
  return path.split('/').pop() ?? path
}
