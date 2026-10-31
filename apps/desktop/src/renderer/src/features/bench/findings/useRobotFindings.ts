// SOLUSDEV-321 P2-T7 — the Findings pane's data. One `GET /findings?status=open&robot=` per
// connected robot, refetched when the findings live key moves (the pane mounts the project
// stream that bumps it) — never polled. A failed read is "unavailable", never "nothing found".
import { useCallback, useEffect, useState } from 'react'
import { SEVERITIES, type Severity } from '@solus/shared-types'
import { api } from '../../../lib/api/client'
import { getFinding, listFindings, type Finding } from '../../../lib/api/findings'
import type { BenchSession } from '../../../lib/api/resources'
import { findingsLiveKey } from '../../graph/useFindings'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../graph/workspaceSession'
import { useLiveRevisionSum } from '../../live/useLiveRefetch'
import { useWorkspaceFetchEnabled } from '../../workspace/workspaceOnline'

export interface ConnectedRobot {
  robotId: string
  label: string
}

export interface RobotFindings extends ConnectedRobot {
  status: 'loading' | 'ready' | 'failed'
  findings: Finding[]
}

export interface SeverityGroup {
  severity: Severity
  findings: Finding[]
  count: number
  lastSeen: string
}

/** Each live robot session's root once (a robot, or a bare part bound on its own), headed by
 *  the first session's label. Sim and serial sessions observe no root, so they have none. */
export function connectedRobots(sessions: readonly BenchSession[] | null): ConnectedRobot[] {
  const robots = new Map<string, string>()
  for (const session of sessions ?? [])
    if (
      session.status !== 'ended' &&
      session.robot_entity_id &&
      !robots.has(session.robot_entity_id)
    )
      robots.set(session.robot_entity_id, session.label)
  return [...robots].map(([robotId, label]) => ({ robotId, label }))
}

const newest = (findings: readonly Finding[]): string =>
  findings.reduce((a, b) => (Date.parse(b.last_seen) > Date.parse(a.last_seen) ? b : a)).last_seen

/** critical → warning → info, the empty ones left out; each keeps the read's order. */
export function severityGroups(findings: readonly Finding[]): SeverityGroup[] {
  return [...SEVERITIES].reverse().flatMap((severity) => {
    const group = findings.filter((finding) => finding.severity === severity)
    return group.length
      ? [{ severity, findings: group, count: group.length, lastSeen: newest(group) }]
      : []
  })
}

/** Open findings per connected robot. `refetch` re-reads at once (after an action, or a
 *  `graph.changed` the pane's stream delivers). */
export function useRobotFindings(
  projectId: string | null,
  robots: readonly ConnectedRobot[]
): { groups: RobotFindings[]; refetch: () => void } {
  const generation = useWorkspaceSessionGeneration()
  const enabled = useWorkspaceFetchEnabled()
  const revision = useLiveRevisionSum([projectId ? findingsLiveKey(projectId) : null])
  const [tick, setTick] = useState(0)
  const refetch = useCallback(() => setTick((value) => value + 1), [])
  const robotKey = robots.map((robot) => robot.robotId).join('\n')
  const scope = JSON.stringify([projectId, robotKey, generation])
  const [state, setState] = useState<{
    scope: string
    byRobot: Record<string, Finding[] | null>
  } | null>(null)
  useEffect(() => {
    if (!projectId || !enabled || !robotKey) return
    let active = true
    const ids = robotKey.split('\n')
    void Promise.all(
      ids.map((robot) => listFindings(projectId, { status: 'open', robot }).catch(() => null))
    ).then((lists) => {
      if (active && workspaceSessionGeneration() === generation)
        setState({ scope, byRobot: Object.fromEntries(ids.map((id, i) => [id, lists[i]])) })
    })
    return () => {
      active = false
    }
  }, [projectId, enabled, generation, robotKey, scope, revision, tick])
  const byRobot = state?.scope === scope ? state.byRobot : null
  return {
    groups: robots.map((robot) => {
      const findings = byRobot ? byRobot[robot.robotId] : undefined
      const status = findings === undefined ? 'loading' : findings === null ? 'failed' : 'ready'
      return { ...robot, status, findings: findings ?? [] }
    }),
    refetch
  }
}

/** The finding a signal marker opened, re-read whenever the findings live key moves (it may be
 *  dismissed or resolved, so the open list does not carry it). */
export function useSelectedFinding(
  projectId: string | null,
  findingId: string | null
): { finding: Finding | null; failed: boolean } {
  const generation = useWorkspaceSessionGeneration()
  const revision = useLiveRevisionSum([projectId ? findingsLiveKey(projectId) : null])
  const key = JSON.stringify([projectId, findingId, generation])
  const [state, setState] = useState<{ key: string; finding: Finding | null } | null>(null)
  useEffect(() => {
    if (!projectId || !findingId) return
    let active = true
    void getFinding(projectId, findingId)
      .catch(() => null)
      .then((finding) => {
        if (active && workspaceSessionGeneration() === generation) setState({ key, finding })
      })
    return () => {
      active = false
    }
  }, [projectId, findingId, generation, key, revision])
  const current = state?.key === key ? state : null
  return { finding: current?.finding ?? null, failed: current !== null && current.finding === null }
}

const MAX_MISSING_SIGNALS = 200

/** What the window evaluator could not judge on this robot (`attrs.missing_signals`, served as
 *  the entity's `properties`), read only when the person asks. Null: not assessed yet. */
export async function loadMissingSignals(
  projectId: string,
  robotId: string
): Promise<string[] | null> {
  const entity = await api.request<{ properties?: Record<string, unknown> }>(
    `/projects/${projectId}/entities/${robotId}`
  )
  const listed = entity.properties?.missing_signals
  if (!Array.isArray(listed)) return null
  return listed
    .filter((item): item is string => typeof item === 'string')
    .slice(0, MAX_MISSING_SIGNALS)
}
