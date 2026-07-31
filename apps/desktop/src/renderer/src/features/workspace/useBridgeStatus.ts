// Local-bridge status for the shell pill (SOLUSDEV-154 / BRG-03): polls the
// per-user bridge state every 10 s while the workspace can fetch and a project
// is linked. Degrades to null (⇒ "Bridge offline") when gated or the API is
// unreachable — the pill renders honestly, never a fabricated state.
import { useCallback, useEffect, useState } from 'react'
import { getBridgeStatus, type BridgeStatus } from '../../lib/api/resources'
import { useInterval } from '../../lib/useInterval'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export const BRIDGE_POLL_MS = 10_000

export type BridgePillState = 'offline' | 'ready' | 'busy' | 'attention'

/** Pure pill mapping: disconnected → offline; any busy server wins; any
 *  error/not_launched server needs attention; otherwise ready. */
export function pillState(status: BridgeStatus | null): BridgePillState {
  if (!status?.connected) return 'offline'
  if (status.servers.some((s) => s.state === 'busy')) return 'busy'
  if (status.servers.some((s) => s.state === 'error' || s.state === 'not_launched')) {
    return 'attention'
  }
  return 'ready'
}

export function useBridgeStatus(projectId: string | null): BridgeStatus | null {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const enabled = fetchEnabled && projectId !== null
  // Keyed by project so a stale status can never leak across a project switch;
  // gating is derived at render time (no setState-in-effect).
  const [result, setResult] = useState<{ projectId: string; status: BridgeStatus } | null>(null)

  const load = useCallback((): void => {
    if (!projectId) return
    getBridgeStatus(projectId)
      .then((status) => setResult({ projectId, status }))
      .catch(() => setResult(null))
  }, [projectId])

  useEffect(() => {
    if (enabled) load()
  }, [enabled, load])

  useInterval(load, BRIDGE_POLL_MS, enabled)
  return enabled && result?.projectId === projectId ? result.status : null
}
