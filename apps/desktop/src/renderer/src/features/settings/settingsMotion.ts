// Settings motion (SOLUSDEV-318), the Home house pattern (homeMotion.ts): a
// capped stagger for rows, and the pure bookkeeping that lets a card animate
// OUT before it unmounts. The keyframes live in settings.css.
export const SETTINGS_STAGGER_MS = 35
export const SETTINGS_STAGGER_CAP = 8
/** Matches `.settings-reveal[data-leaving]` in settings.css. */
export const SETTINGS_EXIT_MS = 220

export function settingsStagger(index: number): React.CSSProperties {
  return {
    animationDelay: `${Math.min(index, SETTINGS_STAGGER_CAP) * SETTINGS_STAGGER_MS}ms`
  }
}

/** True when motion should be skipped: the OS asks, or there is no media API (tests). */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export interface Presence<T> {
  key: string
  item: T
  leaving: boolean
}

/**
 * The list to render: every current item (entering or staying, with its
 * latest value) plus each item that just left, kept at its old position and
 * marked `leaving` so it can play its exit before being dropped.
 */
export function mergePresence<T>(
  previous: readonly Presence<T>[],
  next: readonly T[],
  keyOf: (item: T) => string
): Presence<T>[] {
  const nextByKey = new Map(next.map((item) => [keyOf(item), item]))
  const result: Presence<T>[] = next.map((item) => ({ key: keyOf(item), item, leaving: false }))
  previous.forEach((entry, index) => {
    if (nextByKey.has(entry.key)) return
    result.splice(Math.min(index, result.length), 0, { ...entry, leaving: true })
  })
  return result
}
