// Expand-in / collapse-out wrappers for Settings (SOLUSDEV-318): a single
// disclosure (`Reveal`, e.g. Edit team) and a keyed list whose items animate
// out before unmounting (`RevealList`, the Needs-attention cards). The motion
// is `.settings-reveal` in settings.css; under reduced motion exits are instant.
import { useEffect, useState, type ReactNode } from 'react'
import {
  mergePresence,
  prefersReducedMotion,
  SETTINGS_EXIT_MS,
  type Presence
} from './settingsMotion'

function exitDelay(): number {
  return prefersReducedMotion() ? 0 : SETTINGS_EXIT_MS
}

export function Reveal({
  open,
  children
}: {
  open: boolean
  children: ReactNode
}): React.JSX.Element | null {
  const [shown, setShown] = useState(open)
  // Opening mounts at once (render-time adjust, React's documented pattern).
  if (open && !shown) setShown(true)
  const leaving = shown && !open
  useEffect(() => {
    if (!leaving) return
    const timer = setTimeout(() => setShown(false), exitDelay())
    return () => clearTimeout(timer)
  }, [leaving])
  if (!shown) return null
  return (
    <div className="settings-reveal" data-leaving={leaving || undefined}>
      <div>{children}</div>
    </div>
  )
}

export interface RevealListProps<T> {
  items: readonly T[]
  keyOf: (item: T) => string
  renderItem: (item: T) => React.JSX.Element
  /** The list is a labelled section (and scroll anchor) while it has entries. */
  id?: string
  label?: string
  gap?: number
}

export function RevealList<T>({
  items,
  keyOf,
  renderItem,
  id,
  label,
  gap = 10
}: RevealListProps<T>): React.JSX.Element | null {
  const [source, setSource] = useState(items)
  const [entries, setEntries] = useState<Presence<T>[]>(() => mergePresence([], items, keyOf))
  if (source !== items) {
    setSource(items)
    setEntries(mergePresence(entries, items, keyOf))
  }
  const anyLeaving = entries.some((e) => e.leaving)
  useEffect(() => {
    if (!anyLeaving) return
    const timer = setTimeout(() => setEntries((now) => now.filter((e) => !e.leaving)), exitDelay())
    return () => clearTimeout(timer)
  }, [anyLeaving])
  // Nothing to show (and nothing leaving): no box, so no empty gap in a flex parent.
  if (entries.length === 0) return null
  return (
    <section
      id={id}
      aria-label={label}
      style={{ display: 'flex', flexDirection: 'column', gap, scrollMarginTop: 16 }}
    >
      {entries.map((e) => (
        <div key={e.key} className="settings-reveal" data-leaving={e.leaving || undefined}>
          <div>{renderItem(e.item)}</div>
        </div>
      ))}
    </section>
  )
}
