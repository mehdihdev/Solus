// Live counts for the Context Model screen (API.md §2.3/§2.5): the linked
// project's entity/relation stats plus its connected sources. Degrades to
// `offline` when the workspace isn't linked (dev bypass), no project is
// selected, or the API is unreachable — callers then render the honest
// sign-in/connect empty state, never placeholder robot data (SOLUSDEV-152).
import { useEffect, useState } from 'react'
import { getProject, listSources } from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type GraphSummaryStatus = 'loading' | 'ready' | 'offline'

export interface GraphSummary {
  status: GraphSummaryStatus
  entityCount: number
  relationCount: number
  sourceCount: number
}

const ZERO_COUNTS = { entityCount: 0, relationCount: 0, sourceCount: 0 } as const

export function useGraphSummary(): GraphSummary {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const [summary, setSummary] = useState<GraphSummary>({
    status: fetchEnabled && projectId ? 'loading' : 'offline',
    ...ZERO_COUNTS
  })

  useEffect(() => {
    if (!fetchEnabled || !projectId) {
      setSummary({ status: 'offline', ...ZERO_COUNTS })
      return
    }
    let cancelled = false
    setSummary({ status: 'loading', ...ZERO_COUNTS })
    Promise.all([getProject(projectId), listSources(projectId)])
      .then(([detail, sources]) => {
        if (cancelled) return
        setSummary({
          status: 'ready',
          entityCount: detail.stats.entities,
          relationCount: detail.stats.relations,
          sourceCount: sources.length
        })
      })
      .catch(() => {
        if (!cancelled) setSummary({ status: 'offline', ...ZERO_COUNTS })
      })
    return () => {
      cancelled = true
    }
  }, [fetchEnabled, projectId])

  return summary
}
