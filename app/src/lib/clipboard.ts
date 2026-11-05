import type { ChatMessage, GeneratedDocDetail } from './api'

/** Copia al portapapeles; si la API moderna no está disponible, usa el método clásico. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    area.remove()
    return ok
  }
}

const refs = (r: number[]) => (r.length ? ' ' + r.map((n) => `[${n}]`).join('') : '')

/** Apuntes o resumen como texto plano, con las referencias [n] y la lista de fuentes citadas. */
export function docAsText(d: Pick<GeneratedDocDetail, 'title' | 'sections' | 'citations'>): string {
  const out = [d.title, '']
  for (const s of d.sections) {
    out.push(s.title)
    if (s.prose) out.push(s.points.map((p) => p.text + refs(p.refs)).join(' '))
    else for (const p of s.points) out.push(`- ${p.text}${refs(p.refs)}`)
    out.push('')
  }
  return (out.join('\n') + '\n' + citationsAsText(d.citations)).trim()
}

/** Respuesta del asistente: ⟦n⟧ → [n] y fuentes al final. */
export function answerAsText(m: Pick<ChatMessage, 'content' | 'citations'>): string {
  const body = m.content.replace(/⟦(\d+)⟧/g, '[$1]')
  return (body + '\n\n' + citationsAsText(m.citations)).trim()
}

function citationsAsText(cs: { ref: number; source_title: string }[]): string {
  if (!cs.length) return ''
  const seen = new Map<string, number[]>()
  for (const c of [...cs].sort((a, b) => a.ref - b.ref)) {
    seen.set(c.source_title, [...(seen.get(c.source_title) ?? []), c.ref])
  }
  return [...seen].map(([t, r]) => `${r.map((n) => `[${n}]`).join('')} ${t}`).join('\n')
}
