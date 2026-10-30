// History client (SOLUSDEV-320). Hand-written to docs/api/solus.md §9: the
// project's activities with `entity_ids` and `why_ref`, cursor-paginated.
import { api, type ApiClient, type Page } from './client'

export interface HistoryRow {
  id: string
  type: string
  // Null for rows without an actor (`sync.completed`) or without a domain (edge decisions).
  domain: string | null
  actor_id: string | null
  project_id: string
  payload: Record<string, unknown>
  /** Graph entity ids the row touches. */
  entity_ids: string[]
  /** A conversation id, decision entry id or finding id — the "why". */
  why_ref: string | null
  created_at: string
}

export interface HistoryFilters {
  since?: string
  entity?: string
  domain?: string
  actor?: string
  cursor?: string
  limit?: number
}

const FILTER_KEYS = ['since', 'entity', 'domain', 'actor', 'cursor', 'limit'] as const

function historyQuery(filters: HistoryFilters): string {
  const params = new URLSearchParams()
  for (const key of FILTER_KEYS) {
    const value = filters[key]
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

/** One page of history rows; `meta.next_cursor` continues it. */
export function listHistory(
  projectId: string,
  filters: HistoryFilters = {},
  client: ApiClient = api
): Promise<Page<HistoryRow[]>> {
  return client.requestPage<HistoryRow[]>(`/projects/${projectId}/history${historyQuery(filters)}`)
}
