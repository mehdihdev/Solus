// Live pairing preview for the teleoperation confirmation: every refresh is a
// NEW preview (new preview_id), so Start always posts a fresh one.
import { useCallback, useEffect, useRef, useState } from 'react'
import { previewTeleop, type TeleopPreview } from '../../lib/api/resources'

export const PREVIEW_REFRESH_MS = 500

export function useTeleopPreview(
  projectId: string,
  leaderSessionId: string,
  followerSessionId: string,
  paused: boolean
): {
  preview: TeleopPreview | null
  error: string | null
  refresh: () => Promise<void>
} {
  const [preview, setPreview] = useState<TeleopPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const live = useRef(true)
  const refresh = useCallback(async (): Promise<void> => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const next = await previewTeleop(projectId, {
        leader_session_id: leaderSessionId,
        follower_session_id: followerSessionId
      })
      if (!live.current) return
      setPreview(next)
      setError(null)
    } catch {
      if (!live.current) return
      // Never keep a (possibly ready) preview the server can no longer stand behind.
      setPreview(null)
      setError('The pairing preview could not be loaded.')
    } finally {
      inFlight.current = false
    }
  }, [projectId, leaderSessionId, followerSessionId])
  useEffect(() => {
    live.current = true
    if (paused) return
    void refresh()
    const timer = setInterval(() => void refresh(), PREVIEW_REFRESH_MS)
    return () => {
      live.current = false
      clearInterval(timer)
    }
  }, [refresh, paused])
  return { preview, error, refresh }
}
