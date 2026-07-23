// Overview data for the open project (SOLUSDEV-164): the project's detail
// (name, description, entity/relation stats) plus its connected sources, so the
// Project hub can orient the user before they dive into a domain. Degrades to
// `offline` when the workspace can't fetch (dev bypass / unreachable API) or no
// project is selected — the hub then shows an honest "select a project" state,
// never fabricated data (mirrors useGraphSummary, SOLUSDEV-152).
import { useCallback, useEffect, useState } from 'react'
import { getProject, listSources, type Source } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type ProjectOverviewStatus = 'loading' | 'ready' | 'offline'

export interface ProjectOverview {
  status: ProjectOverviewStatus
  id: string | null
  name: string
  description: string | null
  entityCount: number
  relationCount: number
  sources: Source[]
  refresh: () => Promise<void>
}

const EMPTY = {
  name: '',
  description: null as string | null,
  entityCount: 0,
  relationCount: 0,
  sources: [] as Source[]
}

export function useProjectOverview(): ProjectOverview {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const fallbackName = useWorkspaceStore((s) => s.project?.name ?? '')
  const [status, setStatus] = useState<ProjectOverviewStatus>(
    fetchEnabled && projectId ? 'loading' : 'offline'
  )
  const [data, setData] = useState(EMPTY)

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled || !projectId) {
      setStatus('offline')
      setData(EMPTY)
      return
    }
    try {
      const [detail, sources] = await Promise.all([getProject(projectId), listSources(projectId)])
      setData({
        name: detail.name,
        description: detail.description,
        entityCount: detail.stats.entities,
        relationCount: detail.stats.relations,
        sources
      })
      setStatus('ready')
    } catch {
      setStatus('offline')
      setData(EMPTY)
    }
  }, [fetchEnabled, projectId])

  useEffect(() => {
    void load()
  }, [load])

  return {
    status,
    id: projectId,
    ...data,
    name: status === 'ready' ? data.name : fallbackName,
    refresh: load
  }
}
