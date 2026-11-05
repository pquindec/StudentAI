import { useState } from 'react'
import { es } from '../i18n/es'
import { copyText } from '../lib/clipboard'
import { Button } from './ui'

/** Copia un texto al portapapeles y lo confirma durante un momento. */
export function CopyButton({ text, className = '' }: { text: () => string; className?: string }) {
  const [done, setDone] = useState(false)
  return (
    <Button
      variant="ghost"
      className={className}
      onClick={() =>
        void copyText(text()).then((ok) => {
          if (!ok) return
          setDone(true)
          window.setTimeout(() => setDone(false), 1500)
        })
      }
    >
      {done ? es.common.copied : es.common.copy}
    </Button>
  )
}
