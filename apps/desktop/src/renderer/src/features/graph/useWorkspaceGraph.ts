import { useEffect, useRef, useState } from 'react'
import { apiBaseUrl, createApiClient, type ApiClient } from '../../lib/api/client'
import {
  getProject,
  listAllEntities,
  listAllSources,
  type ProjectDetail,
  type Relation,
  type Source
} from '../../lib/api/resources'
import { listAllRelations } from '../../lib/api/workspace'
import { classifyFetchError } from '../../lib/api/errors'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { liveKeys } from '../../store/liveRevisionStore'
import { useLiveRevisionSum } from '../live/useLiveRefetch'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { countsOf, graphVersionOf, GRAPH_CACHE_TTL_MS } from './graphCache'
import { useSourceViewVersion } from './sourceViewEvents'

export interface GraphSummary {
  status: 'loading' | 'ready' | 'offline' | 'error'
  entityCount: number
  relationCount: number
  sourceCount: number
  entities: import('../../lib/api/resources').Entity[] | null
}

export interface WorkspaceGraph extends GraphSummary {
  relations: Relation[]
  /** The project's source bindings (SOLUSDEV-250 P5 account anchors); `[]` when unread. */
  sources: Source[]
  errorMessage: string | null
}

const EMPTY: WorkspaceGraph = {
  status: 'offline',
  entities: null,
  relations: [],
  sources: [],
  entityCount: 0,
  relationCount: 0,
  sourceCount: 0,
  errorMessage: null
}

const retained = new Map<string, { graph: WorkspaceGraph; version: string; fetchedAt: number }>()
let generation = 0

export function clearWorkspaceGraphCache(): void {
  retained.clear()
  generation += 1
}

/** Drop one project's retained snapshot (its graph is gone with the project — SOLUSDEV-242). */
export function forgetWorkspaceGraph(projectId: string): void {
  retained.delete(projectId)
}

useAuthStore.subscribe((next, previous) => {
  if (next.user?.email !== previous.user?.email || next.status !== previous.status)
    clearWorkspaceGraphCache()
})

async function readGraph(
  projectId: string,
  client: ApiClient,
  isCurrent: () => boolean,
  force = false
): Promise<WorkspaceGraph> {
  let detail: ProjectDetail
  try {
    detail = await getProject(projectId, client)
  } catch (error) {
    if (isCurrent()) retained.delete(projectId)
    return { ...EMPTY, status: classifyFetchError(error) === 'unauthorized' ? 'error' : 'offline' }
  }
  const cached = retained.get(projectId)
  const version = graphVersionOf(detail)
  if (!force && cached?.version === version && Date.now() - cached.fetchedAt < GRAPH_CACHE_TTL_MS)
    return cached.graph
  return readSnapshot(projectId, detail, client, isCurrent)
}

async function readSnapshot(
  projectId: string,
  detail: ProjectDetail,
  client: ApiClient,
  isCurrent: () => boolean
): Promise<WorkspaceGraph> {
  const [entities, relations, sources] = await Promise.allSettled([
    listAllEntities(projectId, client),
    listAllRelations(projectId, client),
    listAllSources(projectId, client)
  ])
  const complete = entities.status === 'fulfilled' && relations.status === 'fulfilled'
  const graph: WorkspaceGraph = {
    ...countsOf(detail),
    status: 'ready',
    entities: complete ? entities.value : null,
    relations: complete ? relations.value : [],
    // Presentation only — a missing source list never gates the graph.
    sources: sources.status === 'fulfilled' ? sources.value : [],
    errorMessage:
      relations.status === 'rejected' ? 'Could not load graph links. Reload to try again.' : null
  }
  if (complete && isCurrent())
    retained.set(projectId, { graph, version: graphVersionOf(detail), fetchedAt: Date.now() })
  return graph
}

function useDetailRevision(projectId: string | null): number {
  return useLiveRevisionSum([projectId ? liveKeys.projectDetail(projectId) : null])
}

/** Keep the last complete snapshot during a refresh; never mix projects or partial links. */
export function useWorkspaceGraph(revision = 0, validation = 0): WorkspaceGraph {
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const viewVersion = useSourceViewVersion(projectId)
  const enabled = useWorkspaceFetchEnabled()
  const identity = useAuthStore((s) => `${s.status}:${s.user?.email ?? ''}`)
  // A live project-detail hint (sources/project changed) re-runs the cheap
  // version check: counts re-read, the entity list only when its version moved.
  const detailRevision = useDetailRevision(projectId)
  const [snapshot, setSnapshot] = useState<{
    projectId: string
    identity: string
    graph: WorkspaceGraph
  } | null>(null)
  // A graph event is authoritative even when MAX(updated_at) is unchanged.
  const previousRevision = useRef(revision)
  const previousView = useRef(viewVersion)
  useEffect(() => {
    if (!projectId || !enabled) return
    let active = true
    const epoch = generation
    const isCurrent = (): boolean => active && epoch === generation
    // A new snapshot must not join an older request in the shared client's GET cache.
    const client = createApiClient({
      baseUrl: apiBaseUrl,
      getToken: () => {
        if (!isCurrent()) throw new Error('The graph read has expired.')
        return useAuthStore.getState().accessToken
      }
    })
    const force = previousRevision.current !== revision || previousView.current !== viewVersion
    previousRevision.current = revision
    previousView.current = viewVersion
    void readGraph(projectId, client, isCurrent, force).then((graph) => {
      if (active && epoch === generation) setSnapshot({ projectId, identity, graph })
    })
    return () => {
      active = false
    }
  }, [projectId, enabled, revision, identity, validation, viewVersion, detailRevision])
  if (!projectId || !enabled) return EMPTY
  if (snapshot?.projectId === projectId && snapshot.identity === identity) return snapshot.graph
  return retained.get(projectId)?.graph ?? { ...EMPTY, status: 'loading' }
}
