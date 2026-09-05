// Per-project source management (SOLUSDEV-164). Lists the sources connected to
// the open project and exposes the actions the Sources page needs: sync now and
// disconnect. Disconnect RETAINS already-synced graph data by default (the
// source's entities are orphaned into manual nodes, not deleted). Degrades to
// `offline` (dev bypass / no project / unreachable API) like the other
// workspace hooks (SOLUSDEV-152) so the page shows honest empty states.
import { useCallback, useEffect, useState } from 'react'
import { useInterval } from '../../lib/useInterval'
import { disconnectSource, listSources, triggerSync, type Source } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

/** How often the list re-reads itself so status, entity counts and last-synced
 *  stay live without a click. This polls OUR api only — it never makes the
 *  connector talk to the provider. The real syncing is the worker's per-minute
 *  `scheduled_change_detection` cron, which only does work when the upstream
 *  actually changed; polling a rate-capped CAD API every 10s would not survive
 *  contact with Onshape. Matches BRIDGE_POLL_MS. */
export const SOURCES_POLL_MS = 10_000

export type ProjectSourcesStatus = 'loading' | 'ready' | 'offline'

export interface ProjectSourcesActions {
  refresh: () => Promise<void>
  syncNow: (sourceId: string) => Promise<boolean>
  disconnect: (sourceId: string) => Promise<boolean>
}

export interface ProjectSourcesData {
  status: ProjectSourcesStatus
  sources: Source[]
  actions: ProjectSourcesActions
}

export function useProjectSources(): ProjectSourcesData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const [status, setStatus] = useState<ProjectSourcesStatus>(
    fetchEnabled && projectId ? 'loading' : 'offline'
  )
  const [sources, setSources] = useState<Source[]>([])

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled || !projectId) {
      setStatus('offline')
      setSources([])
      return
    }
    try {
      const next = await listSources(projectId)
      // A response for a project the user has since left must never paint
      // its documents over the new project's (SOLUSDEV-242).
      if (useWorkspaceStore.getState().project?.id !== projectId) return
      setSources(next)
      setStatus('ready')
    } catch {
      if (useWorkspaceStore.getState().project?.id !== projectId) return
      // Now that this also runs on a 10s timer, a single failed refresh must not
      // blank a list that is already on screen — one blip would otherwise wipe
      // the page and then restore it a moment later. Only report offline when
      // there was nothing to show in the first place.
      setSources((previous) => {
        setStatus(previous.length > 0 ? 'ready' : 'offline')
        return previous
      })
    }
  }, [fetchEnabled, projectId])

  useEffect(() => {
    void load()
  }, [load])

  // Keep the page live. A refresh that fails leaves the previous list on screen
  // rather than blanking it — see `load`'s offline branch, which only fires for
  // a genuinely disabled fetch.
  useInterval(() => void load(), SOURCES_POLL_MS, fetchEnabled && projectId !== null)

  // Run a source mutation, refresh the list, and report success as a boolean.
  const runAction = useCallback(
    async (action: (pid: string) => Promise<unknown>): Promise<boolean> => {
      if (!projectId) return false
      try {
        await action(projectId)
        await load().catch(() => undefined)
        return true
      } catch {
        return false
      }
    },
    [projectId, load]
  )

  const actions: ProjectSourcesActions = {
    refresh: load,
    syncNow: (sourceId) => runAction((pid) => triggerSync(pid, sourceId)),
    disconnect: (sourceId) =>
      runAction((pid) => disconnectSource(pid, sourceId, { retainEntities: true }))
  }

  return { status, sources, actions }
}
