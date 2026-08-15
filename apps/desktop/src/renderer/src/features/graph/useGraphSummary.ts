// Live summary for the Context Model screen: counts from getProject (whose
// payload already carries the sources array — no second sources request) plus
// the full entity list for the list view. Degrades honestly: `offline` when
// the workspace isn't linked, no project is selected, or the API can't answer;
// `error` when the API answers with a refusal (saying "can't reach the API"
// there would be a lie); and a failed LIST call keeps status `ready` with
// `entities: null` — the counts and the list are independent truths.
import { useEffect, useState } from 'react'
import { getProject, listAllEntities, type Entity } from '../../lib/api/resources'
import { classifyFetchError } from '../../lib/api/errors'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type GraphSummaryStatus = 'loading' | 'ready' | 'offline' | 'error'

export interface GraphSummary {
  status: GraphSummaryStatus
  entityCount: number
  relationCount: number
  sourceCount: number
  /** The project's entities, or null when the list call failed (counts may still be honest). */
  entities: Entity[] | null
}

const ZERO_COUNTS = {
  entityCount: 0,
  relationCount: 0,
  sourceCount: 0,
  entities: null
} as const

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
    void Promise.allSettled([getProject(projectId), listAllEntities(projectId)]).then(
      ([detail, entities]) => {
        if (cancelled) return
        if (detail.status === 'rejected') {
          const status = classifyFetchError(detail.reason) === 'unauthorized' ? 'error' : 'offline'
          setSummary({ status, ...ZERO_COUNTS })
          return
        }
        setSummary({
          status: 'ready',
          entityCount: detail.value.stats.entities,
          relationCount: detail.value.stats.relations,
          sourceCount: detail.value.sources.length,
          entities: entities.status === 'fulfilled' ? entities.value : null
        })
      }
    )
    return () => {
      cancelled = true
    }
  }, [fetchEnabled, projectId])

  return summary
}
