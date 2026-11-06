import type { Deck } from './api'

export const isDeckGenerating = (d: Pick<Deck, 'status'>) =>
  d.status === 'queued' || d.status === 'running'

/** Intervalo hasta el próximo repaso, corto: «<1 min», «10 min», «3 h», «4 d», «2 meses», «1,5 años». */
export function formatInterval(seconds: number): string {
  const min = seconds / 60
  if (min < 1) return '<1 min'
  if (min < 60) return `${Math.round(min)} min`
  const h = min / 60
  if (h < 24) return `${Math.round(h)} h`
  const d = h / 24
  if (d < 30) return `${Math.round(d)} d`
  if (d < 365) {
    const m = Math.round(d / 30)
    return m === 1 ? '1 mes' : `${m} meses`
  }
  const y = Math.round((d / 365) * 10) / 10
  return `${y.toLocaleString('es-ES')} ${y === 1 ? 'año' : 'años'}`
}

/** Minutos de estudio redondeados: «45 min», «1 h 20 min». */
export function formatStudy(ms: number): string {
  const total = Math.round(ms / 60_000)
  const h = Math.floor(total / 60)
  const m = total % 60
  if (!h) return `${m} min`
  return m ? `${h} h ${m} min` : `${h} h`
}

/** Porcentaje (0–100) sin decimales; null si no hay base. */
export function percent(part: number, total: number): number | null {
  return total > 0 ? Math.round((part / total) * 100) : null
}

/** Atajos de teclado del repaso: espacio muestra la respuesta; 1–4 valoran. */
export function ratingFromKey(key: string): 1 | 2 | 3 | 4 | null {
  return key === '1' || key === '2' || key === '3' || key === '4'
    ? (Number(key) as 1 | 2 | 3 | 4)
    : null
}
