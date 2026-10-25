// SOLUSDEV-320 P4-T3 — open findings per subject for the card badges. One
// `GET /findings?status=open` per project load, grouped client-side; the live
// stream bumps `findingsLiveKey` on `graph.changed` and `finding.*` to refetch.
import { useCallback, useEffect, useState } from 'react'
import { severityRank, type Severity } from '@solus/shared-types'
import { listFindings, type Finding } from '../../lib/api/findings'
import { useLiveRevisionSum } from '../live/useLiveRefetch'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from './workspaceSession'

export interface FindingBadge {
  severity: Severity
  count: number
}

export type FindingsBySubject = ReadonlyMap<string, FindingBadge>

export const findingsLiveKey = (projectId: string): string => `project:${projectId}:findings`

const EMPTY: FindingsBySubject = new Map()

/** Worst severity and open count per subject id. Pure. */
export function groupFindingsBySubject(findings: readonly Finding[]): FindingsBySubject {
  const grouped = new Map<string, FindingBadge>()
  for (const finding of findings)
    for (const subject of finding.subjects) {
      const previous = grouped.get(subject)
      const worse = previous && severityRank(previous.severity) >= severityRank(finding.severity)
      grouped.set(subject, {
        severity: worse ? previous.severity : finding.severity,
        count: (previous?.count ?? 0) + 1
      })
    }
  return grouped
}

/** Errors read as "no findings"; a stale project or session never repopulates. */
export function useFindings(projectId: string | null): {
  bySubject: FindingsBySubject
  refetch: () => void
} {
  const generation = useWorkspaceSessionGeneration()
  const enabled = useWorkspaceFetchEnabled()
  const revision = useLiveRevisionSum([projectId ? findingsLiveKey(projectId) : null])
  const [tick, setTick] = useState(0)
  const refetch = useCallback(() => setTick((value) => value + 1), [])
  const [state, setState] = useState<{ projectId: string; bySubject: FindingsBySubject } | null>(
    null
  )
  useEffect(() => {
    if (!projectId || !enabled) return
    let active = true
    void listFindings(projectId, { status: 'open' })
      .then(groupFindingsBySubject, () => EMPTY)
      .then((bySubject) => {
        if (active && workspaceSessionGeneration() === generation)
          setState({ projectId, bySubject })
      })
    return () => {
      active = false
    }
  }, [projectId, enabled, generation, revision, tick])
  return { bySubject: state?.projectId === projectId ? state.bySubject : EMPTY, refetch }
}
