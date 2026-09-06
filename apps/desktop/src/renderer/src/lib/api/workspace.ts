import { api, type ApiClient } from './client'
import type { Relation } from './resources'

export interface Point {
  x: number
  y: number
}

export interface WorkspaceLayout {
  version: number
  positions: Record<string, Point>
}

/** Complete graph links for containment; navigation never calls a connector. */
export async function listAllRelations(
  projectId: string,
  client: ApiClient = api
): Promise<Relation[]> {
  const edges: Relation[] = []
  const seen = new Set<string>()
  let cursor: string | null = null
  do {
    const params = new URLSearchParams({ limit: '500' })
    if (cursor) params.set('cursor', cursor)
    const page = await client.requestPage<Relation[]>(
      `/projects/${projectId}/relations?${params.toString()}`
    )
    edges.push(...page.data)
    cursor = page.meta.has_next ? (page.meta.next_cursor ?? null) : null
    if (page.meta.has_next && (!cursor || seen.has(cursor))) {
      throw new Error('Invalid relation pagination cursor')
    }
    if (cursor) seen.add(cursor)
  } while (cursor)
  return edges
}

export function getWorkspaceLayout(
  projectId: string,
  client: ApiClient = api
): Promise<WorkspaceLayout> {
  return client.request<WorkspaceLayout>(`/projects/${projectId}/workspace-layout`)
}

export function saveWorkspaceLayout(
  projectId: string,
  layout: WorkspaceLayout,
  client: ApiClient = api
): Promise<WorkspaceLayout> {
  return client.request<WorkspaceLayout>(`/projects/${projectId}/workspace-layout`, {
    method: 'PUT',
    body: layout
  })
}
