// Per-project source management (SOLUSDEV-164). Lists the sources connected to
// the open project and exposes the actions the Sources page needs: sync now and
// disconnect. Disconnect RETAINS already-synced graph data by default (the
// source's entities are orphaned into manual nodes, not deleted). Degrades to
// `offline` (dev bypass / no project / unreachable API) like the other
// workspace hooks (SOLUSDEV-152) so the page shows honest empty states.
import { useCallback, useEffect, useState } from 'react'
import { disconnectSource, listSources, triggerSync, type Source } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

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
      setSources(await listSources(projectId))
      setStatus('ready')
    } catch {
      setStatus('offline')
      setSources([])
    }
  }, [fetchEnabled, projectId])

  useEffect(() => {
    void load()
  }, [load])

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
