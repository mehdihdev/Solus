// UNWIRED since SOLUSDEV-152 removed the scripted chat composer: no production
// caller until SOLUSDEV-132/134 rebuilds the real SOL chat input around it.
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
  /** S1-W3: one tier up for this message (the composer's "Think harder"). */
  thinkHarder: boolean
}

const NO_OVERRIDE: OverrideState = { complexity: null, type: null, thinkHarder: false }

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
  const trimmed = query.trim()
  // Empty input shows no preview — reset during render (React's "adjust state on
  // change" pattern), not in the effect.
  if (!trimmed && preview !== null) setPreview(null)

  useEffect(() => {
    // ANY input/override change invalidates whatever is in flight immediately —
    // not just when the next timer fires (review fix: no stale-preview window).
    seq.current += 1
    if (!trimmed) return
    const timer = setTimeout(() => {
      const mine = seq.current
      classifyQuery({
        query: trimmed,
        ...(override.complexity ? { complexity: override.complexity } : {}),
        ...(override.type ? { type: override.type } : {}),
        ...(override.thinkHarder ? { think_harder: true } : {})
      })
        .then((p) => {
          if (seq.current === mine) setPreview(p)
        })
        .catch(() => {
          if (seq.current === mine) setPreview(null)
        })
    }, CLASSIFY_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [trimmed, override])

  return {
    preview,
    override,
    setOverride: (patch) => setOverrideState((prev) => ({ ...prev, ...patch })),
    resetOverride: () => setOverrideState(NO_OVERRIDE)
  }
}
