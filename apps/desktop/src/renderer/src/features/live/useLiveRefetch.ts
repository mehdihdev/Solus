// Re-run a REST load when the live revision of any watched key moves (ADR-037).
// The initial load stays the caller's own effect; this only answers hints.
import { useEffect, useRef } from 'react'
import { useLiveRevisionStore } from '../../store/liveRevisionStore'

type WatchedKey = string | null

/** The sum of the watched keys' revisions: it only grows, so any bump changes it,
 *  and several keys bumped in one coalesced burst still read as one change. */
export function useLiveRevisionSum(keys: readonly WatchedKey[]): number {
  return useLiveRevisionStore((state) =>
    keys.reduce<number>((sum, key) => sum + (key === null ? 0 : (state.revisions[key] ?? 0)), 0)
  )
}

export function useLiveRefetch(
  keys: readonly WatchedKey[],
  refetch: () => void,
  enabled = true
): void {
  const sum = useLiveRevisionSum(keys)
  const identity = keys.join('|')
  const latest = useRef(refetch)
  useEffect(() => {
    latest.current = refetch
  })
  // `handled` is the revision sum the caller's data already reflects. It only
  // advances while enabled, so a bump that arrived while disabled still refetches
  // once on enable (e.g. a member promoted to admin whose invites bumped earlier).
  const seen = useRef({ identity, handled: sum })
  useEffect(() => {
    const previous = seen.current
    if (previous.identity !== identity) {
      seen.current = { identity, handled: sum }
      return
    }
    if (!enabled) return
    seen.current = { identity, handled: sum }
    if (previous.handled !== sum) latest.current()
  }, [identity, sum, enabled])
}
