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
  const seen = useRef({ identity, sum })
  useEffect(() => {
    const previous = seen.current
    seen.current = { identity, sum }
    if (previous.identity === identity && previous.sum !== sum && enabled) latest.current()
  }, [identity, sum, enabled])
}
