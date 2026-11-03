import { es } from '../i18n/es'
import { formatDuration } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { useRecording } from '../lib/recording'
import { Button } from './ui'

export function LevelMeter({ level }: { level: number }) {
  // Escala perceptiva: los niveles de voz típicos (0,05–0,3) ocupan la mayor parte de la barra.
  const pct = Math.min(100, Math.round(Math.sqrt(level) * 100))
  return (
    <div
      role="meter"
      aria-label={es.recording.level}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="h-1.5 w-28 overflow-hidden rounded bg-white/30"
    >
      <div
        className="h-full bg-white transition-[width] duration-100"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

/** Indicador permanente mientras se graba, visible en cualquier pantalla. */
export function RecordingBar() {
  const rec = useRecording()
  const navigate = useNavigate()
  const { status } = rec
  if (status.state === 'idle' && !rec.busy) return null
  const paused = status.state === 'paused'

  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-center gap-4 px-6 py-2 text-sm text-white ${paused ? 'bg-amber-600' : 'bg-red-600'}`}
    >
      <span className="flex items-center gap-2 font-medium">
        <span
          aria-hidden
          className={`size-2.5 rounded-full bg-white ${paused ? '' : 'animate-pulse'}`}
        />
        {rec.busy && status.state === 'idle'
          ? es.recording.stopping
          : paused
            ? es.recording.paused
            : es.recording.recording}
      </span>
      <button
        type="button"
        className="truncate hover:underline"
        onClick={() => navigate({ name: 'recordings' })}
      >
        {status.title}
      </button>
      <span className="font-mono tabular-nums">{formatDuration(status.elapsed_ms)}</span>
      {!paused && <LevelMeter level={status.level} />}
      {status.error ? (
        <span className="truncate">{status.error}</span>
      ) : (
        !paused &&
        !status.heard &&
        status.elapsed_ms > 3000 && <span className="font-medium">{es.recording.noSignal}</span>
      )}
      <div className="ml-auto flex gap-2">
        <Button
          className="!bg-white/15 !text-white hover:!bg-white/25"
          disabled={rec.busy}
          onClick={() => void rec.pause(paused)}
        >
          {paused ? es.recording.resume : es.recording.pause}
        </Button>
        <Button
          className="!bg-white !text-red-700 hover:!bg-red-50"
          disabled={rec.busy}
          onClick={() => void rec.stop()}
        >
          {es.recording.stop}
        </Button>
      </div>
    </div>
  )
}
