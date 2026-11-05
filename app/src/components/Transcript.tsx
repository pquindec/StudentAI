import { type RefObject, useEffect, useState } from 'react'
import { es } from '../i18n/es'
import {
  api,
  native,
  nativeError,
  type Source,
  type SourceAudio,
  type SourceContent,
  type SttLanguage,
} from '../lib/api'
import { formatBytes, formatDay, formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { errorMessage, useQuery } from '../lib/useQuery'
import { Button, Card, ConfirmButton, ErrorText, inputClass } from './ui'

/** Reproductor del audio normalizado, retranscripción y exportación. */
export function AudioPanel({
  source,
  audioRef,
  onTime,
  onChanged,
  startAt,
}: {
  source: Source
  audioRef: RefObject<HTMLAudioElement | null>
  onTime: (ms: number) => void
  onChanged: () => void
  /** Posición inicial (ms), p. ej. al abrir la fuente desde una cita. */
  startAt?: number
}) {
  const navigate = useNavigate()
  const info = useQuery(() => api.systemInfo(), [])
  const dataDir = info.data?.data_dir
  // Se vuelve a consultar al cambiar el estado: tras transcribir se borra el original.
  const audio = useQuery(
    () => api.sourceAudio(source.id),
    [source.id, source.status, source.processed_at],
  )
  const hasAudio = audio.data != null && audio.data.state !== 'deleted'
  const src = useQuery(
    () =>
      native && dataDir && hasAudio
        ? native.mediaUrl(`${dataDir}/sources/${source.id}/normalized.wav`)
        : Promise.resolve(null),
    [dataDir, source.id, hasAudio],
  )
  const [language, setLanguage] = useState<SttLanguage>('auto')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const meta = source.metadata as Record<string, unknown>
  const state = typeof meta.transcription === 'string' ? meta.transcription : null
  const busy = source.status === 'pending' || source.status === 'processing'

  const retranscribe = async () => {
    setError(null)
    try {
      await api.transcribe(source.id, language)
      onChanged()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const exportAs = async (format: 'txt' | 'srt') => {
    setError(null)
    setNotice(null)
    try {
      const file = await api.exportSource(source.id, format)
      const path = native ? await native.saveText(file.filename, file.content) : null
      if (path) setNotice(es.transcript.exported(path))
    } catch (e) {
      setError(e instanceof Error || typeof e === 'string' ? nativeError(e) : errorMessage(e))
    }
  }

  return (
    <Card className="space-y-3">
      <h2 className="text-sm font-medium">{es.transcript.player}</h2>
      {src.data ? (
        <audio
          ref={audioRef}
          controls
          preload="metadata"
          src={src.data}
          className="w-full"
          onTimeUpdate={(e) => onTime(e.currentTarget.currentTime * 1000)}
          onLoadedMetadata={(e) => {
            if (startAt != null) e.currentTarget.currentTime = startAt / 1000
          }}
        />
      ) : audio.data?.state === 'deleted' ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{es.transcript.audioDeleted}</p>
      ) : (
        <p className="text-xs text-zinc-500">
          {src.loading || audio.loading ? '' : es.transcript.noPlayer}
        </p>
      )}
      {hasAudio && audio.data && (
        <AudioRetention
          audio={audio.data}
          onDelete={async () => {
            await api.deleteSourceAudio(source.id)
            audio.reload()
          }}
        />
      )}
      {state && es.transcript.status[state] && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {es.transcript.status[state]}{' '}
          {state === 'needs_model' && (
            <button
              type="button"
              className="underline"
              onClick={() => navigate({ name: 'recordings' })}
            >
              {es.transcript.goModels}
            </button>
          )}
        </p>
      )}
      {!busy && state !== 'needs_model' && hasAudio && (
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={es.transcript.language}
            className={`${inputClass} w-auto`}
            value={language}
            onChange={(e) => setLanguage(e.target.value as SttLanguage)}
          >
            {(Object.keys(es.stt.languages) as SttLanguage[]).map((l) => (
              <option key={l} value={l}>
                {es.stt.languages[l]}
              </option>
            ))}
          </select>
          <Button onClick={() => void retranscribe()} title={es.transcript.retranscribeHint}>
            {es.transcript.retranscribe}
          </Button>
        </div>
      )}
      {source.version != null && native && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-zinc-500">{es.transcript.export}:</span>
          <Button variant="ghost" onClick={() => void exportAs('txt')}>
            {es.transcript.exportTxt}
          </Button>
          <Button variant="ghost" onClick={() => void exportAs('srt')}>
            {es.transcript.exportSrt}
          </Button>
        </div>
      )}
      {notice && (
        <p className="text-xs break-all text-emerald-700 dark:text-emerald-400">{notice}</p>
      )}
      <ErrorText>{error}</ErrorText>
    </Card>
  )
}

function AudioRetention({
  audio,
  onDelete,
}: {
  audio: SourceAudio
  onDelete: () => Promise<void>
}) {
  if (!audio.expires_at && !audio.deletable) return null
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
      {audio.expires_at && (
        <span className="flex-1">{es.transcript.audioUntil(formatDay(audio.expires_at))}</span>
      )}
      {audio.deletable && (
        <ConfirmButton
          label={es.transcript.deleteAudio(formatBytes(audio.bytes))}
          title={es.transcript.deleteAudioTitle}
          body={es.transcript.deleteAudioBody}
          onConfirm={onDelete}
        />
      )}
    </div>
  )
}

/**
 * Transcripción sincronizada: cada frase con su marca de tiempo; clic para saltar en el audio y
 * resaltado de la frase que suena. El texto se muestra siempre como texto (nunca HTML).
 */
export function TranscriptView({
  content,
  currentMs,
  onSeek,
}: {
  content: SourceContent
  currentMs: number
  onSeek: (ms: number) => void
}) {
  const segs = content.segments
  const activeIndex = segs.findIndex(
    (s) =>
      s.start_ms != null && s.start_ms <= currentMs && (s.end_ms == null || currentMs < s.end_ms),
  )
  useEffect(() => {
    if (activeIndex < 0) return
    document
      .getElementById(`seg-${segs[activeIndex].ordinal}`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeIndex, segs])

  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {segs.map((seg, i) => {
        // Línea en blanco entre segmentos = párrafo nuevo (pausa en la clase).
        const gap =
          i > 0 && content.text.slice(segs[i - 1].char_end, seg.char_start).includes('\n\n')
        return (
          <div
            key={seg.ordinal}
            id={`seg-${seg.ordinal}`}
            className={`flex gap-3 rounded px-1 ${gap ? 'mt-4' : ''} ${
              i === activeIndex ? 'bg-accent-100 dark:bg-accent-700/30' : ''
            }`}
          >
            {seg.start_ms != null ? (
              <button
                type="button"
                aria-label={es.transcript.seek(formatDuration(seg.start_ms))}
                className="shrink-0 pt-px font-mono text-xs text-accent-700 tabular-nums hover:underline dark:text-accent-300"
                onClick={() => onSeek(seg.start_ms!)}
              >
                {formatDuration(seg.start_ms)}
              </button>
            ) : (
              <span className="w-10 shrink-0" />
            )}
            <p className="whitespace-pre-wrap">{seg.text}</p>
          </div>
        )
      })}
    </div>
  )
}
