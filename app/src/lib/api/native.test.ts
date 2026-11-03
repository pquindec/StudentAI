import { describe, expect, it, vi } from 'vitest'
import { importedSourceId } from '../recording'
import { desktopNative, nativeError } from './native'

describe('desktopNative', () => {
  it('envía destino y micrófono al comando start_recording', async () => {
    const invoke = vi.fn().mockResolvedValue({ state: 'recording' })
    await desktopNative(invoke).start({ subject_id: 's', title: 'Clase' }, 'coreaudio:42')
    expect(invoke).toHaveBeenCalledWith('start_recording', {
      request: { device_id: 'coreaudio:42', target: { subject_id: 's', title: 'Clase' } },
    })
  })

  it('usa el micrófono predeterminado si no se elige ninguno', async () => {
    const invoke = vi.fn().mockResolvedValue({})
    await desktopNative(invoke).start({ subject_id: 's', title: 'T' })
    expect(invoke.mock.calls[0][1].request.device_id).toBeNull()
  })

  it('pausa y reanuda con el mismo comando', async () => {
    const invoke = vi.fn().mockResolvedValue({})
    await desktopNative(invoke).pause(true)
    expect(invoke).toHaveBeenCalledWith('pause_recording', { resume: true })
  })

  it('guarda exportaciones con el diálogo nativo', async () => {
    const invoke = vi.fn().mockResolvedValue('/Users/x/clase.srt')
    const path = await desktopNative(invoke).saveText('clase.srt', '1\n')
    expect(invoke).toHaveBeenCalledWith('save_text_file', {
      defaultName: 'clase.srt',
      content: '1\n',
    })
    expect(path).toBe('/Users/x/clase.srt')
  })

  it('muestra los errores de Rust tal cual', () => {
    expect(nativeError('No hay ningún micrófono disponible')).toBe(
      'No hay ningún micrófono disponible',
    )
  })
})

describe('importedSourceId', () => {
  it('solo devuelve id si la importación fue correcta', () => {
    const ok = { recording_id: 'r', status: 201, body: { id: 'src1' }, warning: null }
    expect(importedSourceId(ok)).toBe('src1')
    expect(importedSourceId({ ...ok, status: 400 })).toBeNull()
    expect(importedSourceId(null)).toBeNull()
  })
})
