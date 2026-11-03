import { useState } from 'react'
import { Sidebar, type Section } from './components/Sidebar'
import { useBackendStatus } from './lib/backendStatus'
import { NavContext, type Route, sectionOf } from './lib/nav'
import { ComingSoon } from './pages/ComingSoon'
import { Dashboard } from './pages/Dashboard'
import { Import } from './pages/Import'
import { Library } from './pages/Library'
import { SourceDetail } from './pages/SourceDetail'
import { SubjectDetail } from './pages/SubjectDetail'
import { Subjects } from './pages/Subjects'

/** Fase del plan (TASKS.md) en la que se construye cada sección pendiente. */
const PHASE: Partial<Record<Section, number>> = {
  recordings: 3,
  notes: 4,
  summaries: 4,
  assistant: 5,
  exams: 6,
  flashcards: 7,
  stats: 7,
  settings: 8,
}

function Page({ route, status }: { route: Route; status: ReturnType<typeof useBackendStatus> }) {
  switch (route.name) {
    case 'dashboard':
      return <Dashboard status={status} />
    case 'subjects':
      return <Subjects />
    case 'subject':
      return <SubjectDetail key={route.id} id={route.id} />
    case 'import':
      return 'subjectId' in route ? (
        <Import key={route.subjectId ?? ''} subjectId={route.subjectId} unitId={route.unitId} />
      ) : (
        <Import />
      )
    case 'library':
      return 'subjectId' in route ? (
        <Library
          key={`${route.subjectId}-${route.unitId}`}
          subjectId={route.subjectId}
          unitId={route.unitId}
        />
      ) : (
        <Library />
      )
    case 'source':
      return <SourceDetail key={route.id} id={route.id} />
    default:
      return <ComingSoon section={route.name} phase={PHASE[route.name] ?? 0} />
  }
}

export default function App() {
  const [route, setRoute] = useState<Route>({ name: 'dashboard' })
  const status = useBackendStatus()
  const ready = status.state === 'ready'

  return (
    <NavContext.Provider value={setRoute}>
      <div className="flex h-full">
        <Sidebar
          current={sectionOf(route)}
          onSelect={(name) => setRoute({ name })}
          status={status}
        />
        <main className="flex-1 overflow-y-auto">
          {ready || route.name === 'dashboard' ? <Page route={route} status={status} /> : null}
        </main>
      </div>
    </NavContext.Provider>
  )
}
