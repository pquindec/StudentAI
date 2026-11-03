import type { GeneratedDoc } from './api'

/** El documento sigue generándose (en cola o en curso). */
export const isBusy = (d: GeneratedDoc) => d.status === 'queued' || d.status === 'running'
