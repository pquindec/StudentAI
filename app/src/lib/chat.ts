import type { ChatMessage, ChatScope } from './api'

/** Trozo de una respuesta: texto o un grupo de referencias seguidas (⟦1⟧⟦2⟧ → [1, 2]). */
export type Part = { text: string } | { refs: number[] }

const REF = /⟦(\d+)⟧/g

/** Separa el texto de las marcas de cita que guarda el backend. */
export function splitRefs(content: string): Part[] {
  const parts: Part[] = []
  let last = 0
  for (const m of content.matchAll(REF)) {
    const at = m.index ?? 0
    if (at > last) parts.push({ text: content.slice(last, at) })
    const n = Number(m[1])
    const prev = parts[parts.length - 1]
    if (prev && 'refs' in prev && at === last) {
      if (!prev.refs.includes(n)) prev.refs.push(n)
    } else {
      parts.push({ refs: [n] })
    }
    last = at + m[0].length
  }
  if (last < content.length) parts.push({ text: content.slice(last) })
  return parts
}

export const isAnswering = (m: Pick<ChatMessage, 'status'>) =>
  m.status === 'queued' || m.status === 'streaming'

/** Ámbito vacío = toda la biblioteca. */
export function scopeFor(subjectId: string, sourceIds: string[]): ChatScope {
  return {
    subject_id: subjectId || null,
    source_ids: subjectId ? sourceIds : [],
    unit_ids: [],
    exclude_source_ids: [],
  }
}
