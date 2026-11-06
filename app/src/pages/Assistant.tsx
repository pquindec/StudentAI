import { useCallback, useEffect, useRef, useState } from 'react'
import { CitationPanel, Refs } from '../components/Citations'
import { CopyButton } from '../components/CopyButton'
import {
  Button,
  Card,
  ConfirmButton,
  ErrorText,
  Field,
  inputClass,
  PageHeader,
} from '../components/ui'
import { es } from '../i18n/es'
import { api, type ChatMessage, type ChatScope, type ChatThreadDetail } from '../lib/api'
import { answerAsText } from '../lib/clipboard'
import { isAnswering, scopeFor, splitRefs } from '../lib/chat'
import { errorMessage, useQuery } from '../lib/useQuery'

const POLL_MS = 400
const THREAD_KEY = 'assistant.thread'

function remembered(): string | null {
  try {
    return localStorage.getItem(THREAD_KEY)
  } catch {
    return null
  }
}

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(THREAD_KEY, id)
    else localStorage.removeItem(THREAD_KEY)
  } catch {
    // sin almacenamiento local: solo se pierde recordar la última conversación
  }
}

/** Selector de ámbito: toda la biblioteca, una asignatura o algunas fuentes de ella. */
function ScopePicker({ scope, onChange }: { scope: ChatScope; onChange: (s: ChatScope) => void }) {
  const subjects = useQuery(() => api.listSubjects(false), [])
  const subjectId = scope.subject_id ?? ''
  const sources = useQuery(
    () =>
      subjectId
        ? api.listSources({ subject_id: subjectId, status: 'ready', limit: 200 })
        : Promise.resolve(null),
    [subjectId],
  )
  const picked = scope.source_ids ?? []
  const toggle = (id: string) =>
    onChange(
      scopeFor(subjectId, picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]),
    )
  return (
    <div className="space-y-3">
      <Field label={es.chat.scope}>
        <select
          className={inputClass}
          value={subjectId}
          onChange={(e) => onChange(scopeFor(e.target.value, []))}
        >
          <option value="">{es.chat.library}</option>
          {subjects.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </Field>
      {subjectId && (sources.data?.items.length ?? 0) > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            {picked.length ? es.chat.onlySources : es.chat.allSources}
          </div>
          <ul className="max-h-48 space-y-1 overflow-y-auto text-sm">
            {sources.data?.items.map((s) => (
              <li key={s.id}>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={picked.includes(s.id)}
                    onChange={() => toggle(s.id)}
                  />
                  <span className="truncate">{s.title}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Answer({
  m,
  selected,
  onSelect,
}: {
  m: ChatMessage
  selected: number | null
  onSelect: (ref: number) => void
}) {
  const known = new Map(m.citations.map((c) => [c.ref, c]))
  if (m.status === 'not_found')
    return <p className="text-zinc-600 dark:text-zinc-400">{es.chat.notFound}</p>
  if (m.status === 'failed') return <ErrorText>{m.error ?? es.chat.failed}</ErrorText>
  if (m.status === 'queued' || (m.status === 'streaming' && !m.content)) {
    return <p className="animate-pulse text-zinc-500">{m.progress_message ?? es.chat.thinking}</p>
  }
  const kind = m.status === 'done' ? m.stats.kind : 'answer'
  const label = kind === 'created' ? es.chat.created : kind === 'general' ? es.chat.general : null
  return (
    <div className="space-y-2">
      {label && (
        <p
          className={`rounded-md px-2 py-1 text-xs font-medium ${
            kind === 'general'
              ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
              : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
          }`}
        >
          {label}
        </p>
      )}
      <p className="leading-relaxed whitespace-pre-wrap">
        {splitRefs(m.content).map((p, i) =>
          'text' in p ? (
            <span key={i}>{p.text}</span>
          ) : (
            <Refs key={i} refs={p.refs} known={known} selected={selected} onSelect={onSelect} />
          ),
        )}
        {m.status === 'streaming' && <span className="ml-0.5 animate-pulse">▍</span>}
      </p>
      {m.status === 'cancelled' && <p className="text-xs text-zinc-500">{es.chat.cancelled}</p>}
      {m.status === 'done' && (
        <div className="flex items-center gap-2">
          <p className="flex-1 text-xs text-zinc-500">
            {m.model ? es.chat.model(m.model) : ''}
            {m.stats.invented_cites > 0 ? ` · ${es.chat.discarded(m.stats.invented_cites)}` : ''}
          </p>
          <CopyButton
            className="text-xs"
            text={() => (label ? `${label}\n\n` : '') + answerAsText(m)}
          />
        </div>
      )}
    </div>
  )
}

export function Assistant() {
  const threads = useQuery(() => api.listThreads(), [])
  const rag = useQuery(() => api.ragStatus(), [])
  const [threadId, setThreadId] = useState<string | null>(remembered)
  const [thread, setThread] = useState<ChatThreadDetail | null>(null)
  const [draftScope, setDraftScope] = useState<ChatScope>(scopeFor('', []))
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [selected, setSelected] = useState<{ msg: string; ref: number } | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const open = useCallback((id: string | null) => {
    setThreadId(id)
    remember(id)
    setSelected(null)
    setError(null)
    if (!id) setThread(null)
  }, [])

  // Carga la conversación elegida (si ya no existe, se vuelve a una nueva).
  useEffect(() => {
    if (!threadId) return
    let alive = true
    api.getThread(threadId).then(
      (t) => alive && setThread(t),
      () => alive && open(null),
    )
    return () => {
      alive = false
    }
  }, [threadId, open])

  // Mientras se genera la respuesta, se consulta cada POLL_MS (texto en directo).
  const pending = thread?.messages.find((m) => m.role === 'assistant' && isAnswering(m))
  const reloadThreads = threads.reload
  useEffect(() => {
    if (!pending) return
    const t = window.setInterval(() => {
      api.getMessage(pending.id).then(
        (m) => {
          setThread((th) =>
            th ? { ...th, messages: th.messages.map((x) => (x.id === m.id ? m : x)) } : th,
          )
          if (!isAnswering(m)) reloadThreads()
        },
        () => undefined,
      )
    }, POLL_MS)
    return () => window.clearInterval(t)
  }, [pending?.id, reloadThreads]) // eslint-disable-line react-hooks/exhaustive-deps

  // Índice en preparación: se refresca el aviso hasta que termine.
  const indexing = rag.data?.pending ?? 0
  const reloadRag = rag.reload
  useEffect(() => {
    if (!indexing) return
    const t = window.setInterval(() => reloadRag(), 3000)
    return () => window.clearInterval(t)
  }, [indexing, reloadRag])

  const count = thread?.messages.length ?? 0
  const lastContent = thread?.messages[count - 1]?.content
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' })
  }, [count, lastContent])

  const scope = thread?.scope ?? draftScope
  const changeScope = async (s: ChatScope) => {
    setError(null)
    if (!thread) {
      setDraftScope(s)
      return
    }
    try {
      const t = await api.updateThread(thread.id, { scope: s })
      setThread({ ...thread, scope: t.scope })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const send = async () => {
    const q = text.trim()
    if (!q || sending || pending) return
    setSending(true)
    setError(null)
    try {
      const id = thread?.id ?? (await api.createThread(draftScope)).id
      await api.ask(id, q)
      setText('')
      const t = await api.getThread(id)
      setThread(t)
      if (id !== threadId) open(id)
      reloadThreads()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSending(false)
    }
  }

  const selectedMsg = thread?.messages.find((m) => m.id === selected?.msg)
  const cite = selectedMsg?.citations.find((c) => c.ref === selected?.ref)

  return (
    <div className="mx-auto max-w-7xl px-10 py-10">
      <PageHeader title={es.chat.title} subtitle={es.chat.subtitle} />
      <div className="grid gap-6 lg:grid-cols-[15rem_1fr_20rem]">
        <aside className="space-y-3">
          <Button variant="primary" className="w-full justify-center" onClick={() => open(null)}>
            {es.chat.newThread}
          </Button>
          <div className="text-xs font-medium text-zinc-500">{es.chat.threads}</div>
          {threads.data?.length === 0 && (
            <p className="text-sm text-zinc-500">{es.chat.noThreads}</p>
          )}
          <ul className="space-y-0.5">
            {threads.data?.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => open(t.id)}
                  className={`w-full truncate rounded px-2 py-1.5 text-left text-sm ${
                    t.id === threadId
                      ? 'bg-accent-100 text-accent-700 dark:bg-accent-700/30 dark:text-accent-100'
                      : 'hover:bg-zinc-200/70 dark:hover:bg-zinc-800'
                  }`}
                >
                  {t.title}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="flex min-w-0 flex-col gap-4">
          {indexing > 0 && <p className="text-xs text-zinc-500">{es.chat.indexing(indexing)}</p>}
          {rag.data && !rag.data.embed_ready && rag.data.embed_problem && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {es.chat.wordsOnly(rag.data.embed_problem)}
            </p>
          )}
          <Card className="min-h-[24rem] space-y-5">
            {!thread || thread.messages.length === 0 ? (
              <p className="text-sm text-zinc-500">
                {rag.data?.sources === 0 ? es.chat.needSources : es.chat.empty}
              </p>
            ) : (
              thread.messages.map((m) => (
                <div key={m.id} className="text-[15px]">
                  <div className="mb-1 text-xs font-medium text-zinc-500">
                    {m.role === 'user' ? es.chat.you : es.chat.assistant}
                  </div>
                  {m.role === 'user' ? (
                    <p className="whitespace-pre-wrap">{m.content}</p>
                  ) : (
                    <Answer
                      m={m}
                      selected={selected?.msg === m.id ? selected.ref : null}
                      onSelect={(ref) => setSelected({ msg: m.id, ref })}
                    />
                  )}
                </div>
              ))
            )}
            <div ref={bottom} />
          </Card>
          <ErrorText>{error}</ErrorText>
          <div className="flex items-end gap-2">
            <textarea
              className={`${inputClass} min-h-[2.5rem] resize-y`}
              rows={2}
              maxLength={4000}
              placeholder={es.chat.placeholder}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void send()
                }
              }}
            />
            {pending ? (
              <Button onClick={() => void api.cancelMessage(pending.id).catch(() => undefined)}>
                {es.chat.stop}
              </Button>
            ) : (
              <Button
                variant="primary"
                disabled={!text.trim() || sending}
                onClick={() => void send()}
              >
                {es.chat.send}
              </Button>
            )}
          </div>
        </section>

        <aside className="space-y-4 self-start lg:sticky lg:top-4">
          <Card>
            <ScopePicker scope={scope} onChange={(s) => void changeScope(s)} />
            {thread && thread.messages.length > 0 && (
              <p className="mt-2 text-xs text-zinc-500">{es.chat.scopeChanged}</p>
            )}
          </Card>
          {selected && <CitationPanel ref_={selected.ref} cite={cite} />}
          {thread && (
            <ConfirmButton
              label={es.chat.deleteThread}
              title={thread.title}
              onConfirm={async () => {
                await api.deleteThread(thread.id)
                open(null)
                reloadThreads()
              }}
            />
          )}
        </aside>
      </div>
    </div>
  )
}
