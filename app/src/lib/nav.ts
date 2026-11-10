import { createContext, useContext } from 'react'
import type { Section } from '../components/Sidebar'

/** Rutas de la app (estado en memoria: una app de escritorio no necesita URLs). */
export type Route =
  | { name: Section }
  | { name: 'subject'; id: string }
  | { name: 'source'; id: string; at?: number }
  | { name: 'document'; id: string; kind: 'notes' | 'summary' }
  | { name: 'exam'; id: string }
  | { name: 'examEditor'; subjectId: string; id?: string }
  | { name: 'attempt'; id: string }
  | { name: 'live'; id: string }
  | { name: 'deck'; id: string }
  | { name: 'review'; subjectId?: string; deckId?: string; back?: Route }
  | { name: 'import'; subjectId?: string; unitId?: string }
  | { name: 'library'; subjectId?: string; unitId?: string }

export const NavContext = createContext<(r: Route) => void>(() => {})

export const useNavigate = () => useContext(NavContext)

/** Sección del menú lateral que se resalta para cada ruta. */
export function sectionOf(r: Route): Section {
  if (r.name === 'subject') return 'subjects'
  if (r.name === 'source') return 'library'
  if (r.name === 'exam' || r.name === 'examEditor' || r.name === 'attempt' || r.name === 'live')
    return 'exams'
  if (r.name === 'deck' || r.name === 'review') return 'flashcards'
  if (r.name === 'document') return r.kind === 'notes' ? 'notes' : 'summaries'
  return r.name
}
