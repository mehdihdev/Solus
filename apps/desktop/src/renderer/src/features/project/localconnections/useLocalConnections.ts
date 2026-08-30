// Local-connection data for a project (SOLUSDEV-72): what the bench can stream
// from (runner, simulators, serial devices) plus the active sessions. Cloned
// from the useBridgeStatus pattern: projectId-keyed result, ~5s poll while the
// workspace can fetch, degrade to null on error — honest offline, never
// fabricated data.
import { useCallback, useEffect, useState } from 'react'
import {
  getBenchSources,
  listBenchSessions,
  listLocalTools,
  type BenchSession,
  type BenchSources,
  type LocalTool
} from '../../../lib/api/resources'
import { useInterval } from '../../../lib/useInterval'
import { useWorkspaceFetchEnabled } from '../../workspace/workspaceOnline'

export const LOCAL_CONNECTIONS_POLL_MS = 5_000

export interface LocalConnections {
  sources: BenchSources
  sessions: BenchSession[]
}

export interface LocalConnectionsResult {
  data: LocalConnections | null
  /** On-demand re-fetch (after starting/stopping a session). */
  refresh: () => void
}

export function useLocalConnections(projectId: string | null): LocalConnectionsResult {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const enabled = fetchEnabled && projectId !== null
  // Keyed by project so a stale result can never leak across a project switch.
  const [result, setResult] = useState<{ projectId: string; data: LocalConnections } | null>(null)

  const load = useCallback((): void => {
    if (!projectId) return
    Promise.all([getBenchSources(projectId), listBenchSessions(projectId, { status: 'active' })])
      .then(([sources, sessions]) => setResult({ projectId, data: { sources, sessions } }))
      .catch(() => setResult(null))
  }, [projectId])

  useEffect(() => {
    if (enabled) load()
  }, [enabled, load])

  useInterval(load, LOCAL_CONNECTIONS_POLL_MS, enabled)

  return {
    data: enabled && result?.projectId === projectId ? result.data : null,
    refresh: load
  }
}

/** The local tools the companion bridge can reach (not project-scoped). One
 *  fetch per mount; null means unknown (gated or unreachable) — never []. */
export function useLocalTools(): LocalTool[] | null {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [tools, setTools] = useState<LocalTool[] | null>(null)

  useEffect(() => {
    if (!fetchEnabled) return
    let active = true
    listLocalTools()
      .then((result) => {
        if (active) setTools(result)
      })
      .catch(() => {
        if (active) setTools(null)
      })
    return () => {
      active = false
    }
  }, [fetchEnabled])

  return tools
}
