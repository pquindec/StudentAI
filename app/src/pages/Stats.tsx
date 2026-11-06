import type { ReactNode } from 'react'
import { useState } from 'react'
import { BarChart } from '../components/BarChart'
import { Card, ErrorText, Field, inputClass, Loading, PageHeader } from '../components/ui'
import { es } from '../i18n/es'
import { api, type Stats as StatsData } from '../lib/api'
import { formatStudy, percent } from '../lib/flashcards'
import { formatDate } from '../lib/format'
import { useNavigate } from '../lib/nav'
import { useQuery } from '../lib/useQuery'
import { CardMix } from './Flashcards'

const RANGES = [7, 30, 90] as const

/** «2026-11-09» → «9 nov» (los días ya vienen en hora local). */
function shortDay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('es', { day: 'numeric', month: 'short' })
}

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card className="space-y-1">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-zinc-500">{hint}</p>}
    </Card>
  )
}

function Content({ s, days }: { s: StatsData; days: number }) {
  const navigate = useNavigate()
  const retention = s.retention == null ? null : Math.round(s.retention * 100)
  const studied = s.cards.new + s.cards.learning + s.cards.mastered
  const mastered = percent(s.cards.mastered, studied)
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile
          label={es.stats.studyTime}
          value={formatStudy(s.study_ms)}
          hint={es.stats.activeDays(s.active_days, days)}
        />
        <Tile label={es.stats.reviews} value={s.reviews.toLocaleString('es-ES')} />
        <Tile
          label={es.stats.retention}
          value={retention == null ? es.stats.none : `${retention} %`}
          hint={es.stats.retentionHint}
        />
        <Tile label={es.stats.streak} value={es.stats.streakN(s.streak)} />
      </div>

      <Card className="space-y-2">
        <h2 className="font-medium">{es.stats.perDay}</h2>
        <p className="text-xs text-zinc-500">{es.stats.studyHint}</p>
        <BarChart
          bars={s.days.map((d) => {
            const min = Math.round(d.study_ms / 60_000)
            return {
              key: d.date,
              label: shortDay(d.date),
              value: min,
              tooltip: es.stats.dayTooltip(shortDay(d.date), min, d.reviews, d.exams),
            }
          })}
          unit={es.stats.minutes}
          everyLabel={days <= 7 ? 1 : days <= 30 ? 7 : 15}
          tableHeaders={[es.stats.date, es.stats.studyTime]}
        />
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-3">
          <h2 className="font-medium">{es.stats.cards}</h2>
          {s.cards.total === 0 ? (
            <p className="text-sm text-zinc-500">{es.stats.noCards}</p>
          ) : (
            <>
              <CardMix counts={s.cards} />
              {mastered != null && (
                <p className="text-xs text-zinc-500">
                  {mastered} % {es.flashcards.counts.mastered.toLowerCase()} ·{' '}
                  {es.flashcards.masteredHint}
                </p>
              )}
              <h3 className="pt-2 text-sm font-medium">{es.stats.forecast}</h3>
              <BarChart
                height={80}
                bars={s.cards.forecast.map((f, i) => ({
                  key: f.date,
                  label: i === 0 ? es.stats.today : shortDay(f.date),
                  value: f.due,
                  tooltip: es.stats.forecastTooltip(
                    i === 0 ? es.stats.today : shortDay(f.date),
                    f.due,
                  ),
                }))}
                unit={(v) => String(v)}
                tableHeaders={[es.stats.date, es.stats.reviews]}
              />
            </>
          )}
        </Card>
        <Card className="space-y-3">
          <h2 className="font-medium">{es.stats.exams}</h2>
          {s.exams_taken === 0 ? (
            <p className="text-sm text-zinc-500">{es.stats.noExams}</p>
          ) : (
            <p className="text-sm">
              {es.stats.examsTaken(s.exams_taken)}
              {s.exam_average != null &&
                ` · ${es.stats.average(s.exam_average.toLocaleString('es-ES'))}`}
            </p>
          )}
          {s.recent_exams.length > 0 && (
            <>
              <h3 className="pt-2 text-sm font-medium">{es.stats.recent}</h3>
              <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                {s.recent_exams.map((e) => (
                  <li key={e.attempt_id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-3 py-1.5 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900"
                      onClick={() => navigate({ name: 'attempt', id: e.attempt_id })}
                    >
                      <span className="min-w-0 flex-1 truncate">{e.title}</span>
                      <span className="text-xs text-zinc-500">{formatDate(e.date)}</span>
                      <span className="w-12 text-right font-medium tabular-nums">
                        {e.grade == null ? es.stats.none : `${e.grade.toLocaleString('es-ES')}/10`}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

export function Stats() {
  const subjects = useQuery(() => api.listSubjects(false), [])
  const [subjectId, setSubjectId] = useState('')
  const [days, setDays] = useState<number>(30)
  const q = useQuery(
    () => api.stats({ subject_id: subjectId || undefined, days }),
    [subjectId, days],
  )
  return (
    <div className="mx-auto max-w-5xl px-10 py-10">
      <PageHeader title={es.stats.title} subtitle={es.stats.subtitle} />
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <Field label={es.stats.subject}>
          <select
            className={`${inputClass} w-auto`}
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
          >
            <option value="">{es.stats.allSubjects}</option>
            {subjects.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={es.stats.range}>
          <select
            className={`${inputClass} w-auto`}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {es.stats.ranges[r]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ErrorText>{q.error}</ErrorText>
      {q.data ? <Content s={q.data} days={days} /> : !q.error && <Loading />}
    </div>
  )
}
