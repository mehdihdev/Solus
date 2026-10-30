// Candidate edge client (SOLUSDEV-320), hand-written to docs/api/relations.md §3.
// Responses are `serialize_relation` shapes, the same `Relation` the canvas draws.
import { api, type ApiClient } from './client'
import type { Relation } from './resources'

export interface EdgeCandidateFilters {
  relation_type?: string
  subject?: string
}

/** Live `inferred` edges below the candidate threshold. */
export function listEdgeCandidates(
  projectId: string,
  filters: EdgeCandidateFilters = {},
  client: ApiClient = api
): Promise<Relation[]> {
  const params = new URLSearchParams()
  if (filters.relation_type) params.set('relation_type', filters.relation_type)
  if (filters.subject) params.set('subject', filters.subject)
  const query = params.toString()
  return client.request<Relation[]>(
    `/projects/${projectId}/edges/candidates${query ? `?${query}` : ''}`
  )
}

/** → `origin: manual`, `confidence: 1.0`; the server emits `graph.changed`. */
export function confirmEdge(
  projectId: string,
  edgeId: string,
  client: ApiClient = api
): Promise<Relation> {
  return client.request<Relation>(`/projects/${projectId}/edges/${edgeId}/confirm`, {
    method: 'POST'
  })
}

/** Soft delete; the server emits `graph.changed`. */
export function declineEdge(
  projectId: string,
  edgeId: string,
  reason?: string,
  client: ApiClient = api
): Promise<Relation> {
  return client.request<Relation>(`/projects/${projectId}/edges/${edgeId}/decline`, {
    method: 'POST',
    body: reason ? { reason } : {}
  })
}
