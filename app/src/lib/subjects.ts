import type { Source, Unit } from './api'

export const isAudio = (s: Source) => s.kind === 'audio' || s.kind === 'recording'

export const SUBJECT_COLORS = [
  '#4f46e5',
  '#0891b2',
  '#059669',
  '#d97706',
  '#dc2626',
  '#db2777',
  '#7c3aed',
]

export type UnitKind = Unit['kind']

/** Jerarquía: un hijo siempre tiene un rango mayor que su padre (igual que el backend). */
export const UNIT_RANK: Record<UnitKind, number> = { course: 0, module: 1, topic: 2 }

/** Unidades ordenadas como árbol (padre antes que hijos) con su profundidad. */
export function unitTree(units: Unit[]): { unit: Unit; depth: number }[] {
  const children = new Map<string | null, Unit[]>()
  for (const u of units) {
    const k = u.parent_id ?? null
    children.set(k, [...(children.get(k) ?? []), u])
  }
  const out: { unit: Unit; depth: number }[] = []
  const seen = new Set<string>()
  const walk = (parent: string | null, depth: number) => {
    const list = [...(children.get(parent) ?? [])].sort(
      (a, b) => a.position - b.position || a.title.localeCompare(b.title, 'es'),
    )
    for (const u of list) {
      if (seen.has(u.id)) continue
      seen.add(u.id)
      out.push({ unit: u, depth })
      walk(u.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
}
