import { useState } from 'react'
import { Sidebar, type Section } from './components/Sidebar'
import { useBackendStatus } from './lib/backendStatus'
import { ComingSoon } from './pages/ComingSoon'
import { Dashboard } from './pages/Dashboard'

/** Fase del plan (TASKS.md) en la que se construye cada sección. */
const PHASE: Record<Exclude<Section, 'dashboard'>, number> = {
  subjects: 2,
  import: 2,
  library: 2,
  recordings: 3,
  notes: 4,
  summaries: 4,
  assistant: 5,
  exams: 6,
  flashcards: 7,
  stats: 7,
  settings: 8,
}

export default function App() {
  const [section, setSection] = useState<Section>('dashboard')
  const status = useBackendStatus()

  return (
    <div className="flex h-full">
      <Sidebar current={section} onSelect={setSection} status={status} />
      <main className="flex-1 overflow-y-auto">
        {section === 'dashboard' ? (
          <Dashboard status={status} />
        ) : (
          <ComingSoon section={section} phase={PHASE[section]} />
        )}
      </main>
    </div>
  )
}
