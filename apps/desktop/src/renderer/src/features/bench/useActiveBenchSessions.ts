// Session discovery is scoped to account/project and independent of selected focus.
import { useEffect, useState } from 'react'
import { listBenchSessions, type BenchSession } from '../../lib/api/resources'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export const ACTIVE_SESSIONS_POLL_MS = 5_000

export function useActiveBenchSessions(
  projectId: string | null,
  enabled: boolean
): BenchSession[] | null {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const generation = useWorkspaceSessionGeneration()
  const scope = JSON.stringify([identity, projectId, generation])
  const on = fetchEnabled && enabled && projectId !== null
  const [result, setResult] = useState<{ scope: string; sessions: BenchSession[] } | null>(null)
  useEffect(() => {
    if (!on || !projectId) return
    let live = true
    let inFlight = false
    const load = async (): Promise<void> => {
      if (inFlight) return
      inFlight = true
      try {
        const sessions = await listBenchSessions(projectId)
        if (!live || workspaceSessionGeneration() !== generation) return
        setResult((previous) => ({
          scope,
          sessions: sessions.filter(
            (session) =>
              session.status !== 'ended' ||
              (previous?.scope === scope &&
                previous.sessions.some((item) => item.id === session.id))
          )
        }))
      } catch {
        if (live && workspaceSessionGeneration() === generation) setResult(null)
      } finally {
        inFlight = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), ACTIVE_SESSIONS_POLL_MS)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [projectId, on, scope, generation])
  return on && result?.scope === scope ? result.sessions : null
}

/** Include observed devices from sessions that disconnected while this view was open. */
export function activeDeviceIds(sessions: readonly BenchSession[] | null): string[] {
  return [...new Set((sessions ?? []).flatMap((session) => session.device_ids))]
}
