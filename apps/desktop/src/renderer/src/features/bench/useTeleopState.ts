// Polls the project's current teleop (running, or last stopped with its reason).
import { useCallback, useEffect, useState } from 'react'
import { getTeleop, type Teleop } from '../../lib/api/resources'

export const TELEOP_POLL_MS = 1_000

export function useTeleopState(
  projectId: string | null,
  enabled: boolean
): { teleop: Teleop | null; refresh: () => void } {
  const [teleop, setTeleop] = useState<Teleop | null>(null)
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => setTick((n) => n + 1), [])
  useEffect(() => {
    if (!enabled || !projectId) return
    let live = true
    let inFlight = false
    const load = async (): Promise<void> => {
      if (inFlight) return
      inFlight = true
      try {
        const next = await getTeleop(projectId)
        if (live) setTeleop(next)
      } catch {
        // Keep the last known state; the next poll retries.
      } finally {
        inFlight = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), TELEOP_POLL_MS)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [projectId, enabled, tick])
  return { teleop: enabled ? teleop : null, refresh }
}
