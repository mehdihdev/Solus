import { useEffect, useRef, useState } from 'react'
import { apiBaseUrl, createApiClient, type ApiClient } from '../../lib/api/client'
import {
  getProject,
  listAllEntities,
  type ProjectDetail,
  type Relation
} from '../../lib/api/resources'
import { listAllRelations } from '../../lib/api/workspace'
import { classifyFetchError } from '../../lib/api/errors'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { countsOf, graphVersionOf, GRAPH_CACHE_TTL_MS } from './graphCache'

export interface GraphSummary {
  status: 'loading' | 'ready' | 'offline' | 'error'
  entityCount: number
  relationCount: number
  sourceCount: number
  entities: import('../../lib/api/resources').Entity[] | null
}

export interface WorkspaceGraph extends GraphSummary {
  relations: Relation[]
  errorMessage: string | null
}

const EMPTY: WorkspaceGraph = {
  status: 'offline',
  entities: null,
  relations: [],
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

useAuthStore.subscribe((next, previous) => {
  if (next.user?.email !== previous.user?.email || next.status !== previous.status)
    clearWorkspaceGraphCache()
})

async function readGraph(
  projectId: string,
  client: ApiClient,
  isCurrent: () => boolean
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
  if (cached?.version === version && Date.now() - cached.fetchedAt < GRAPH_CACHE_TTL_MS)
    return cached.graph
  return readSnapshot(projectId, detail, client, isCurrent)
}

async function readSnapshot(
  projectId: string,
  detail: ProjectDetail,
  client: ApiClient,
  isCurrent: () => boolean
): Promise<WorkspaceGraph> {
  const [entities, relations] = await Promise.allSettled([
    listAllEntities(projectId, client),
    listAllRelations(projectId, client)
  ])
  const complete = entities.status === 'fulfilled' && relations.status === 'fulfilled'
  const graph: WorkspaceGraph = {
    ...countsOf(detail),
    status: 'ready',
    entities: complete ? entities.value : null,
    relations: complete ? relations.value : [],
    errorMessage:
      relations.status === 'rejected' ? 'Could not load graph links. Reload to try again.' : null
  }
  if (complete && isCurrent())
    retained.set(projectId, { graph, version: graphVersionOf(detail), fetchedAt: Date.now() })
  return graph
}

/** Keep the last complete snapshot during a refresh; never mix projects or partial links. */
export function useWorkspaceGraph(revision = 0, validation = 0): WorkspaceGraph {
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const enabled = useWorkspaceFetchEnabled()
  const identity = useAuthStore((s) => `${s.status}:${s.user?.email ?? ''}`)
  const [snapshot, setSnapshot] = useState<{
    projectId: string
    identity: string
    graph: WorkspaceGraph
  } | null>(null)
  const invalidated = useRef(0)
  useEffect(() => {
    if (!projectId || !enabled) return
    let active = true
    const epoch = generation
    if (revision !== invalidated.current) retained.delete(projectId)
    invalidated.current = revision
    const isCurrent = (): boolean => active && epoch === generation
    // A new snapshot must not join an older request in the shared client's GET cache.
    const client = createApiClient({
      baseUrl: apiBaseUrl,
      getToken: () => {
        if (!isCurrent()) throw new Error('The graph read has expired.')
        return useAuthStore.getState().accessToken
      }
    })
    void readGraph(projectId, client, isCurrent).then((graph) => {
      if (active && epoch === generation) setSnapshot({ projectId, identity, graph })
    })
    return () => {
      active = false
    }
  }, [projectId, enabled, revision, identity, validation])
  if (!projectId || !enabled) return EMPTY
  if (snapshot?.projectId === projectId && snapshot.identity === identity) return snapshot.graph
  return retained.get(projectId)?.graph ?? { ...EMPTY, status: 'loading' }
}
