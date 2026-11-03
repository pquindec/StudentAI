import { useEffect, useState } from 'react'
import { AiPanel } from '../components/AiPanel'
import { DocList, GenerateDialog } from '../components/Documents'
import { Button, Card, ErrorText, Field, inputClass, Loading, PageHeader } from '../components/ui'
import { es } from '../i18n/es'
import { api, type DocKind } from '../lib/api'
import { isBusy } from '../lib/documents'
import { useNavigate } from '../lib/nav'
import { useQuery } from '../lib/useQuery'

/** Página de Apuntes o Resúmenes: documentos de una asignatura y botón para generar. */
export function Documents({ kind }: { kind: DocKind }) {
  const navigate = useNavigate()
  const subjects = useQuery(() => api.listSubjects(false), [])
  const [picked, setPicked] = useState('')
  const subjectId = picked || subjects.data?.[0]?.id || ''
  const docs = useQuery(
    () => (subjectId ? api.listDocuments(subjectId) : Promise.resolve([])),
    [subjectId],
  )
  const [open, setOpen] = useState(false)
  const mine = docs.data?.filter((d) => d.kind === kind) ?? []
  const busy = mine.some(isBusy)

  const { reload } = docs
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => reload(), 1500)
    return () => window.clearInterval(t)
  }, [busy, reload])

  const notes = kind === 'notes'
  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <PageHeader
        title={notes ? es.docs.notesTitle : es.docs.summariesTitle}
        subtitle={notes ? es.docs.notesSubtitle : es.docs.summariesSubtitle}
        actions={
          subjectId ? (
            <Button variant="primary" onClick={() => setOpen(true)}>
              {notes ? es.docs.newNotes : es.docs.newSummary}
            </Button>
          ) : undefined
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Card className="min-w-0 space-y-4">
          {subjects.data?.length === 0 ? (
            <div>
              <p className="text-sm">{es.docs.needSubject}</p>
              <Button
                className="mt-3"
                variant="primary"
                onClick={() => navigate({ name: 'subjects' })}
              >
                {es.subjects.new}
              </Button>
            </div>
          ) : (
            <>
              <Field label={es.docs.subject}>
                <select
                  className={`${inputClass} w-auto`}
                  value={subjectId}
                  onChange={(e) => setPicked(e.target.value)}
                >
                  {subjects.data?.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
              <ErrorText>{docs.error ?? subjects.error}</ErrorText>
              {!docs.data ? (
                <Loading />
              ) : mine.length === 0 ? (
                <p className="text-sm text-zinc-500">{es.docs.empty}</p>
              ) : (
                <DocList docs={mine} kind={kind} />
              )}
            </>
          )}
        </Card>
        <aside className="self-start">
          <AiPanel />
        </aside>
      </div>
      {subjectId && (
        <GenerateDialog
          key={`${subjectId}-${String(open)}`}
          open={open}
          kind={kind}
          subjectId={subjectId}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  )
}
