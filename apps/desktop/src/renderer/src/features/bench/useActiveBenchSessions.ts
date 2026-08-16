// Active bench sessions for the device-keyed Bench view (SOLUSDEV-72).
// useBridgeStatus pattern: projectId-keyed, ~5s poll while enabled, null when
// unknown (gated or unreachable) — the caller must not treat null as "none".
import { useCallback, useEffect, useState } from 'react'
import { listBenchSessions, type BenchSession } from '../../lib/api/resources'
import { useInterval } from '../../lib/useInterval'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export const ACTIVE_SESSIONS_POLL_MS = 5_000

export function useActiveBenchSessions(
  projectId: string | null,
  enabled: boolean
): BenchSession[] | null {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const on = fetchEnabled && enabled && projectId !== null
  const [result, setResult] = useState<{ projectId: string; sessions: BenchSession[] } | null>(null)

  const load = useCallback((): void => {
    if (!projectId) return
    listBenchSessions(projectId, { status: 'active' })
      .then((sessions) => setResult({ projectId, sessions }))
      .catch(() => setResult(null))
  }, [projectId])

  useEffect(() => {
    if (on) load()
  }, [on, load])

  useInterval(load, ACTIVE_SESSIONS_POLL_MS, on)

  return on && result?.projectId === projectId ? result.sessions : null
}

/** Unique device ids across the given sessions, in first-seen order. */
export function activeDeviceIds(sessions: readonly BenchSession[] | null): string[] {
  if (!sessions) return []
  return [...new Set(sessions.flatMap((s) => s.device_ids))]
}
