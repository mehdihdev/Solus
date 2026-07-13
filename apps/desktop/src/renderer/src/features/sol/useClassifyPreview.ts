// MO-04: debounced pre-flight classification for the composer. Calls the real
// classify endpoint ~400ms after typing pauses (never per keystroke), drops
// stale responses (latest-wins), and treats failures as "show nothing" — a
// classification hiccup must never block sending. Overrides are per-call state
// held here and reset by the composer after send.
import { useEffect, useRef, useState } from 'react'
import {
  classifyQuery,
  type ClassifyPreview,
  type ComplexityValue,
  type RouteTypeValue
} from '../../lib/api/resources'

export const CLASSIFY_DEBOUNCE_MS = 400

export interface OverrideState {
  complexity: ComplexityValue | null
  type: RouteTypeValue | null
}

const NO_OVERRIDE: OverrideState = { complexity: null, type: null }

export interface ClassifyPreviewState {
  preview: ClassifyPreview | null
  override: OverrideState
  setOverride: (patch: Partial<OverrideState>) => void
  resetOverride: () => void
}

export function useClassifyPreview(query: string): ClassifyPreviewState {
  const [preview, setPreview] = useState<ClassifyPreview | null>(null)
  const [override, setOverrideState] = useState<OverrideState>(NO_OVERRIDE)
  const seq = useRef(0)

  useEffect(() => {
    // ANY input/override change invalidates whatever is in flight immediately —
    // not just when the next timer fires (review fix: no stale-preview window).
    seq.current += 1
    const trimmed = query.trim()
    if (!trimmed) {
      setPreview(null)
      return
    }
    const timer = setTimeout(() => {
      const mine = seq.current
      classifyQuery({
        query: trimmed,
        ...(override.complexity ? { complexity: override.complexity } : {}),
        ...(override.type ? { type: override.type } : {})
      })
        .then((p) => {
          if (seq.current === mine) setPreview(p)
        })
        .catch(() => {
          if (seq.current === mine) setPreview(null)
        })
    }, CLASSIFY_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query, override])

  return {
    preview,
    override,
    setOverride: (patch) => setOverrideState((prev) => ({ ...prev, ...patch })),
    resetOverride: () => setOverrideState(NO_OVERRIDE)
  }
}
