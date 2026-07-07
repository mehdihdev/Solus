// setInterval as a hook (ported from useInterval in TestDesign/app/util.jsx):
// always calls the latest callback, cleans up on unmount, and can be gated.
import { useEffect, useRef } from 'react'

export function useInterval(fn: () => void, ms: number | null, on = true): void {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (!on || ms == null) return
    const id = setInterval(() => ref.current(), ms)
    return () => clearInterval(id)
  }, [ms, on])
}
