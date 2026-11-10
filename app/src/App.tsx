import { CloudConsentProvider } from './components/CloudConsent'
import { useState } from 'react'
import { RecordingBar } from './components/RecordingBar'
import { RecordingProvider } from './components/RecordingProvider'
import { RecoveryDialog } from './components/RecoveryDialog'
import { Sidebar } from './components/Sidebar'
import { useBackendStatus } from './lib/backendStatus'
import { NavContext, type Route, sectionOf } from './lib/nav'
import { Assistant } from './pages/Assistant'
import { AttemptView } from './pages/AttemptView'
import { Dashboard } from './pages/Dashboard'
import { DeckView } from './pages/DeckView'
import { DocumentView } from './pages/DocumentView'
import { Documents } from './pages/Documents'
import { Exams } from './pages/Exams'
import { ExamEditor } from './pages/ExamEditor'
import { ExamView } from './pages/ExamView'
import { Flashcards } from './pages/Flashcards'
import { Import } from './pages/Import'
import { Library } from './pages/Library'
import { LiveRoom } from './pages/LiveRoom'
import { Recordings } from './pages/Recordings'
import { Review } from './pages/Review'
import { Settings } from './pages/Settings'
import { SourceDetail } from './pages/SourceDetail'
import { Stats } from './pages/Stats'
import { SubjectDetail } from './pages/SubjectDetail'
import { Subjects } from './pages/Subjects'

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
    case 'recordings':
      return <Recordings />
    case 'source':
      return <SourceDetail key={`${route.id}-${route.at ?? ''}`} id={route.id} at={route.at} />
    case 'document':
      return <DocumentView key={route.id} id={route.id} />
    case 'assistant':
      return <Assistant />
    case 'exams':
      return <Exams />
    case 'exam':
      return <ExamView key={route.id} id={route.id} />
    case 'examEditor':
      return (
        <ExamEditor
          key={`${route.subjectId}:${route.id ?? 'new'}`}
          subjectId={route.subjectId}
          examId={route.id}
        />
      )
    case 'attempt':
      return <AttemptView key={route.id} id={route.id} />
    case 'live':
      return <LiveRoom key={route.id} id={route.id} />
    case 'flashcards':
      return <Flashcards />
    case 'deck':
      return <DeckView key={route.id} id={route.id} />
    case 'review':
      return (
        <Review
          key={`${route.subjectId ?? ''}-${route.deckId ?? ''}`}
          subjectId={route.subjectId}
          deckId={route.deckId}
          back={route.back}
        />
      )
    case 'stats':
      return <Stats />
    case 'settings':
      return <Settings />
    case 'notes':
    case 'summaries':
      return <Documents key={route.name} kind={route.name === 'notes' ? 'notes' : 'summary'} />
  }
}

export default function App() {
  const [route, setRoute] = useState<Route>({ name: 'dashboard' })
  const status = useBackendStatus()
  const ready = status.state === 'ready'

  return (
    <NavContext.Provider value={setRoute}>
      <RecordingProvider>
        <CloudConsentProvider>
          <div className="flex h-full">
            <Sidebar
              current={sectionOf(route)}
              onSelect={(name) => setRoute({ name })}
              status={status}
            />
            <div className="flex min-w-0 flex-1 flex-col">
              <RecordingBar />
              <main className="flex-1 overflow-y-auto">
                {ready || route.name === 'dashboard' ? (
                  <Page route={route} status={status} />
                ) : null}
              </main>
            </div>
          </div>
          <RecoveryDialog enabled={ready} />
        </CloudConsentProvider>
      </RecordingProvider>
    </NavContext.Provider>
  )
}
