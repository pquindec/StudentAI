import type { Section } from '../components/Sidebar'
import { es } from '../i18n/es'

export function ComingSoon({ section, phase }: { section: Section; phase: number }) {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center px-8 text-center">
      <h1 className="text-xl font-semibold">{es.nav[section]}</h1>
      <p className="mt-2 text-sm text-zinc-500">
        <span className="font-medium text-zinc-700 dark:text-zinc-300">{es.comingSoon.title}.</span>{' '}
        {es.comingSoon.body(phase)}
      </p>
    </div>
  )
}
