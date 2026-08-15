// SOLUS-TU-09 — the Guide data hook.
//
// Fetches one resolved walkthrough. Degrades to `error` (rendered as an honest
// empty state) on any failure rather than showing a fabricated guide — the
// same precision-over-recall posture the backend takes with the KB.
import { useEffect, useState } from 'react'
import { getGuide, type GuideDetail } from './guideApi'

export type GuideStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface GuideState {
  status: GuideStatus
  guide: GuideDetail | null
}

export function useGuide(guideId: string | null, version: string): GuideState {
  const [state, setState] = useState<GuideState>({
    status: guideId ? 'loading' : 'idle',
    guide: null
  })

  useEffect(() => {
    if (!guideId) {
      setState({ status: 'idle', guide: null })
      return
    }
    let cancelled = false
    const controller = new AbortController()
    setState({ status: 'loading', guide: null })
    getGuide(guideId, version, undefined, controller.signal)
      .then((guide) => {
        if (!cancelled) setState({ status: 'ready', guide })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error', guide: null })
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [guideId, version])

  return state
}
